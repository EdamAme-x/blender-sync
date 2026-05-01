from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Callable

from ..domain.entities import CategoryKind, ChannelKind, Packet, Session, SyncConfig
from ..domain.policies.conflict_resolver import (
    ConflictContext,
    ConflictDecision,
    ConflictPolicy,
    IConflictResolver,
)
from ..domain.policies.echo_filter import EchoFilter
from ..domain.policies.lww_resolver import LWWResolver
from ..domain.policies.packet_builder import lww_key
from ..domain.policies.packet_chain import ReceiverChainState
from ..domain.ports import IClock, ICodec, ILogger, ISceneApplier


def _packet_body_for_chain(packet: Packet) -> bytes:
    d = packet.to_wire_dict()
    cleaned = {k: v for k, v in d.items() if k not in ("c", "d")}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ApplyRemotePacketUseCase:
    """Decode → echo filter → chain verify → LWW → scene apply.

    Chain verification: receivers maintain a per-author rolling Adler chain
    (matching what the sender computed). When a packet arrives:
      - If it's CONTROL or FORCE, skip chain verification (control bypasses
        ordering, force packets are full-state and don't need history).
      - If chain==0 (fast/transform channel), no verification.
      - Otherwise, compare seq with expected_seq:
          * == expected: verify chain match, accept, replay chain.
          * <  expected: duplicate/RESEND that already filled a gap, ignore.
          * >  expected: gap detected. Hold this packet and emit NACK.
    """

    def __init__(
        self,
        scene: ISceneApplier,
        codec: ICodec,
        echo_filter: EchoFilter,
        lww: LWWResolver,
        logger: ILogger,
        config: SyncConfig,
        conflict_resolver: IConflictResolver | None = None,
        clock: IClock | None = None,
    ) -> None:
        self._scene = scene
        self._codec = codec
        self._echo = echo_filter
        self._lww = lww
        self._logger = logger
        self._config = config
        self._conflict_resolver = conflict_resolver
        self._clock = clock
        self._control_handler: Callable[[Session, list[dict]], None] | None = None
        self._session: Session | None = None
        self._chains: dict[str, ReceiverChainState] = {}
        self._on_nack: Callable[[str, int, int], None] | None = None

    def set_conflict_resolver(self, resolver: IConflictResolver) -> None:
        self._conflict_resolver = resolver

    def set_control_handler(
        self, session: Session, handler: Callable[[Session, list[dict]], None]
    ) -> None:
        self._session = session
        self._control_handler = handler

    def set_nack_emitter(self, fn: Callable[[str, int, int], None]) -> None:
        """Runtime calls this with (author, first_seq, last_seq) when a gap
        is detected, so the runtime can emit a NACK control packet."""
        self._on_nack = fn

    def reset_chain(self, author: str) -> None:
        """Drop chain state for a peer (e.g. after Force Push aligned us)."""
        self._chains.pop(author, None)

    def _state(self, author: str) -> ReceiverChainState:
        st = self._chains.get(author)
        if st is None:
            st = ReceiverChainState()
            self._chains[author] = st
        return st

    def apply_raw(self, data: bytes) -> None:
        try:
            packet = self._codec.decode(data)
        except Exception as exc:
            self._logger.warning("decode failed: %s", exc)
            return

        if not self._echo.should_accept(packet.author):
            return

        category = packet.category

        if category is CategoryKind.CONTROL:
            self._dispatch_control(packet)
            return

        if not self._chain_verified(packet):
            return

        self._apply_payload(packet)

        # After a force packet, any held-back reliable packets newer
        # than the force seq may now be in-order against the realigned
        # chain. Drain them now so apply order is force-then-followups.
        if packet.force and packet.chain != 0:
            self._drain_held_back(packet.author)

    def _chain_verified(self, packet: Packet) -> bool:
        """Returns True if the packet should be applied now. Side-effects:
          - advances chain for in-order reliable packets
          - holds out-of-order reliable packets and emits NACK
          - drains held-back queue when in-order resumes

        Fast (chain==0) packets travel on a separate seq counter (see
        PacketBuilder) and are accepted unconditionally here — they do
        NOT touch the reliable chain state, so they cannot interfere
        with reliable seq tracking.

        Force packets are special: they ride the reliable seq + chain on
        the sender (so NACK/RESEND continuity is preserved), but the
        whole point of a Force Push is to recover from a stale or
        broken chain. We bypass chain verification and instead realign
        the receiver's chain to the force packet's reported state. Any
        held-back packets older than the force seq are obsolete and
        discarded; later held-backs are drained if they line up.
        """
        if packet.chain == 0:
            return True

        if packet.force:
            self._catch_up_to_force(packet)
            return True

        st = self._state(packet.author)

        if st.is_duplicate(packet.seq):
            self._logger.debug(
                "ignoring duplicate seq=%d from %s", packet.seq, packet.author,
            )
            return False

        if st.is_in_order(packet.seq):
            body = _packet_body_for_chain(packet)
            a, b = st.accept(packet.seq, body)
            actual = (b << 16) | a
            if actual != packet.chain:
                self._logger.warning(
                    "chain mismatch from %s seq=%d expected=%d got=%d",
                    packet.author, packet.seq, actual, packet.chain,
                )
                # Treat as gap: rewind chain and request resend.
                st.expected_seq = packet.seq
                st.last_verified_seq = packet.seq - 1
                st.chain.a = 1
                st.chain.b = 0
                self._emit_nack(packet.author, packet.seq, packet.seq)
                return False
            self._drain_held_back(packet.author)
            return True

        # Gap: seq > expected_seq. Hold this packet, request resend.
        body_bytes = self._codec.encode(packet)
        st.held_back[packet.seq] = body_bytes
        first = st.expected_seq
        last = packet.seq - 1
        if last >= first:
            self._emit_nack(packet.author, first, last)
        return False

    def _catch_up_to_force(self, packet: Packet) -> None:
        """Realign receiver chain state to a force packet.

        Force = "I'm authoritative; whatever you had, replace it." After
        applying, expected_seq jumps to seq+1 and the chain rolling
        state is restored from the force packet's chain field (low 16
        bits = a, high 16 bits = b — same encoding as PacketChain.fold).
        Held-back packets <= seq are now obsolete (they're either
        already represented in the force snapshot or strictly older).
        Newer held-backs are left in place; the caller drains them
        AFTER the force payload is applied so the apply order matches
        the seq order on the wire.
        """
        st = self._state(packet.author)
        st.expected_seq = packet.seq + 1
        st.last_verified_seq = packet.seq
        st.chain.a = packet.chain & 0xFFFF
        st.chain.b = (packet.chain >> 16) & 0xFFFF
        # Discard held-back entries that are now in the past relative
        # to the force snapshot.
        st.held_back = {
            s: data for s, data in st.held_back.items() if s > packet.seq
        }

    def _drain_held_back(self, author: str) -> None:
        st = self._state(author)
        while st.expected_seq in st.held_back:
            data = st.held_back.pop(st.expected_seq)
            try:
                packet = self._codec.decode(data)
            except Exception:
                continue
            body = _packet_body_for_chain(packet)
            a, b = st.accept(packet.seq, body)
            actual = (b << 16) | a
            if actual != packet.chain:
                self._logger.warning(
                    "held-back chain mismatch from %s seq=%d", author, packet.seq,
                )
                st.held_back.clear()
                st.expected_seq = packet.seq + 1
                continue
            self._apply_payload(packet)

    def _emit_nack(self, author: str, first: int, last: int) -> None:
        if self._on_nack is None:
            return
        try:
            self._on_nack(author, first, last)
        except Exception as exc:
            self._logger.warning("nack emit failed: %s", exc)

    def _dispatch_control(self, packet: Packet) -> None:
        if self._control_handler is None or self._session is None:
            return
        try:
            self._control_handler(self._session, [dict(o) for o in packet.ops])
        except Exception as exc:
            self._logger.error("control handler failed: %s", exc)

    def _apply_payload(self, packet: Packet) -> None:
        category = packet.category
        accepted_ops: list[dict[str, Any]] = []
        for op in packet.ops:
            key = lww_key(category, dict(op))
            if packet.force:
                self._lww.should_apply(key, packet.author, packet.seq, packet.ts)
                accepted_ops.append(dict(op))
                continue

            # Run conflict resolver if configured. Otherwise fall back to
            # plain LWW (current behavior).
            if self._conflict_resolver is None:
                if self._lww.should_apply(
                    key, packet.author, packet.seq, packet.ts
                ):
                    accepted_ops.append(dict(op))
                continue

            decision = self._decide_conflict(key, packet)
            if decision is ConflictDecision.APPLY:
                self._lww.force_record(
                    key, packet.author, packet.seq, packet.ts
                )
                accepted_ops.append(dict(op))
            elif decision is ConflictDecision.REJECT:
                continue
            elif decision is ConflictDecision.DEFER:
                # Manual UI will resolve later; do not apply now.
                continue

        if not accepted_ops:
            return

        if packet.force:
            self._logger.info(
                "applying FORCE packet from %s (%s, %d ops)",
                packet.author, category.value, len(accepted_ops),
            )

        self._scene.set_applying_remote(True)
        try:
            self._scene.apply_ops(category, accepted_ops)
        except Exception as exc:
            self._logger.error("apply_ops failed for %s: %s", category, exc)
        finally:
            self._scene.set_applying_remote(False)

    def _decide_conflict(self, key: str, packet: Packet) -> ConflictDecision:
        local = self._lww.get_state(key)
        if local is not None:
            local_seq, local_ts, local_author = local
        else:
            local_seq = local_ts = None
            local_author = None
        ctx = ConflictContext(
            key=key,
            self_peer_id=self._config.peer_id,
            incoming_author=packet.author,
            incoming_seq=packet.seq,
            incoming_ts=packet.ts,
            local_last_edit_ts=local_ts,
            local_last_seq=local_seq,
            local_last_author=local_author,
            now_ts=self._clock.now() if self._clock else packet.ts,
        )
        try:
            return self._conflict_resolver.decide(ctx)
        except Exception as exc:
            self._logger.warning("conflict resolver failed: %s", exc)
            # Safest fallback is plain LWW.
            return (
                ConflictDecision.APPLY
                if self._lww.should_apply(
                    key, packet.author, packet.seq, packet.ts
                )
                else ConflictDecision.REJECT
            )

    def drain(self, queue_get_nowait, max_per_tick: int | None = None) -> int:
        limit = max_per_tick if max_per_tick is not None else self._config.inbound_max_per_tick
        applied = 0
        for _ in range(limit):
            try:
                data = queue_get_nowait()
            except Exception:
                break
            if data is None:
                break
            self.apply_raw(data)
            applied += 1
        return applied


def group_ops_by_category(
    items: list[tuple[CategoryKind, list[dict[str, Any]]]]
) -> dict[CategoryKind, list[dict[str, Any]]]:
    out: dict[CategoryKind, list[dict[str, Any]]] = defaultdict(list)
    for cat, ops in items:
        out[cat].extend(ops)
    return out

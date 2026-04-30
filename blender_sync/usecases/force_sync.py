"""Force Sync UseCases.

ForcePushUseCase
    "Make all peers match MY scene now."
    Builds a full snapshot of every category enabled in SyncFilters and
    sends each as a force=True packet. Receivers bypass LWW and overwrite.

ForcePullUseCase
    "Make MY scene match a peer's now."
    Sends a control PULL_REQUEST. The peer responds with a force-push
    targeted at this peer (broadcast is acceptable since LWW will be
    bypassed and the requestor's local state is intentionally being
    overwritten anyway).

Both honor SyncFilters: a filter that is OFF means that category is
neither pushed nor requested.
"""
from __future__ import annotations

from ..domain.entities import (
    CategoryKind,
    ControlOpKind,
    Packet,
    Session,
    SessionStatus,
    SyncConfig,
)
from ..domain.policies.packet_builder import OutboundHistory, PacketBuilder
from ..domain.ports import (
    IAsyncRunner,
    IClock,
    ICodec,
    ILogger,
    ISceneSnapshot,
    ITransport,
)


def _enabled_categories(config: SyncConfig) -> frozenset[CategoryKind]:
    return config.filters.enabled_categories()


class ForcePushUseCase:
    def __init__(
        self,
        scene: ISceneSnapshot,
        transport: ITransport,
        codec: ICodec,
        clock: IClock,
        logger: ILogger,
        async_runner: IAsyncRunner,
        builder: PacketBuilder,
        config: SyncConfig,
        history: OutboundHistory | None = None,
    ) -> None:
        self._scene = scene
        self._transport = transport
        self._codec = codec
        self._clock = clock
        self._logger = logger
        self._async_runner = async_runner
        self._builder = builder
        self._config = config
        self._history = history

    def execute(self, session: Session) -> int:
        """Push my full scene state to all peers. Returns categories sent."""
        if session.status is not SessionStatus.LIVE:
            self._logger.warning("force push: session not LIVE (status=%s)",
                                 session.status.value)
            return 0

        enabled = _enabled_categories(self._config)
        try:
            grouped = self._scene.build_full_snapshot()
        except Exception as exc:
            self._logger.error("force push: build_full_snapshot failed: %s", exc)
            return 0

        ts = self._clock.now()
        sent = 0
        for category, ops in grouped:
            if category not in enabled or not ops:
                continue
            packet = self._builder.build(category, ops, ts, force=True)
            try:
                data = self._codec.encode(packet)
            except Exception as exc:
                self._logger.error("force push encode %s failed: %s", category, exc)
                continue
            if self._history is not None:
                self._history.record(packet)
            self._async_runner.run_coroutine(
                self._transport.send(packet.channel, data)
            )
            sent += 1
        self._logger.info("force push: sent %d categories", sent)
        return sent


class ForcePullUseCase:
    def __init__(
        self,
        transport: ITransport,
        codec: ICodec,
        clock: IClock,
        logger: ILogger,
        async_runner: IAsyncRunner,
        builder: PacketBuilder,
        config: SyncConfig,
    ) -> None:
        self._transport = transport
        self._codec = codec
        self._clock = clock
        self._logger = logger
        self._async_runner = async_runner
        self._builder = builder
        self._config = config

    def execute(self, session: Session) -> bool:
        """Ask all peers to send their state to overwrite mine."""
        if session.status is not SessionStatus.LIVE:
            self._logger.warning("force pull: session not LIVE (status=%s)",
                                 session.status.value)
            return False

        enabled = _enabled_categories(self._config)
        op = {
            "type": ControlOpKind.PULL_REQUEST.value,
            "categories": [c.value for c in enabled],
        }
        packet = self._builder.build(
            CategoryKind.CONTROL, [op], self._clock.now(), force=False,
        )
        try:
            data = self._codec.encode(packet)
        except Exception as exc:
            self._logger.error("force pull encode failed: %s", exc)
            return False
        self._async_runner.run_coroutine(
            self._transport.send(packet.channel, data)
        )
        self._logger.info("force pull: requested %d categories", len(enabled))
        return True


class ControlMessageHandler:
    """Receives CONTROL category packets and dispatches to the appropriate
    response. Currently:
      - PULL_REQUEST -> trigger ForcePushUseCase
      - PING         -> reply PONG (with original send time echoed)
      - PONG         -> compute round-trip and notify metrics_listener
    """

    def __init__(
        self,
        force_push: ForcePushUseCase,
        transport: ITransport,
        codec: ICodec,
        clock: IClock,
        logger: ILogger,
        async_runner: IAsyncRunner,
        builder: PacketBuilder,
        history: OutboundHistory | None = None,
    ) -> None:
        self._force_push = force_push
        self._transport = transport
        self._codec = codec
        self._clock = clock
        self._logger = logger
        self._async_runner = async_runner
        self._builder = builder
        self._history = history
        self._on_latency = None  # type: ignore[assignment]

    def set_latency_listener(self, fn) -> None:
        self._on_latency = fn

    def set_history(self, history: OutboundHistory) -> None:
        self._history = history

    def handle(self, session: Session, ops: list[dict]) -> None:
        for op in ops:
            t = op.get("type")
            if t == ControlOpKind.PULL_REQUEST.value:
                self._logger.info("received pull_request from peer")
                self._force_push.execute(session)
            elif t == ControlOpKind.PING.value:
                self._reply_pong(op)
            elif t == ControlOpKind.PONG.value:
                self._handle_pong(op)
            elif t == ControlOpKind.NACK.value:
                self._handle_nack(op)
            elif t == ControlOpKind.RESEND.value:
                self._handle_resend(op)

    def _reply_pong(self, op: dict) -> None:
        pong = {"type": ControlOpKind.PONG.value, "t": op.get("t")}
        self._send_control([pong])

    def _handle_pong(self, op: dict) -> None:
        sent_at = op.get("t")
        if isinstance(sent_at, (int, float)) and self._on_latency:
            rtt = max(0.0, self._clock.monotonic() - float(sent_at))
            try:
                self._on_latency(rtt * 1000.0)
            except Exception:
                pass

    def _handle_nack(self, op: dict) -> None:
        if self._history is None:
            self._logger.warning("nack received but no history buffer; ignoring")
            return
        first = int(op.get("from", 0))
        last = int(op.get("to", 0))
        if last < first:
            return
        oldest = self._history.oldest_seq()
        if oldest is not None and first < oldest:
            self._logger.warning(
                "nack range %d-%d falls below history (oldest=%d); peer "
                "should Force Pull to recover", first, last, oldest,
            )
            return
        packets = self._history.range(first, last)
        if not packets:
            self._logger.warning("nack %d-%d: no packets in history", first, last)
            return
        self._logger.info("RESEND %d packets (seq %d-%d)",
                          len(packets), first, last)
        for original in packets:
            self._send_resend(original)

    def _send_resend(self, original: Packet) -> None:
        op = {
            "type": ControlOpKind.RESEND.value,
            "packet": original.to_wire_dict(),
        }
        self._send_control([op])

    def _handle_resend(self, op: dict) -> None:
        wire = op.get("packet")
        if not isinstance(wire, dict):
            return
        try:
            packet = Packet.from_wire_dict(wire)
        except Exception as exc:
            self._logger.warning("malformed RESEND payload: %s", exc)
            return
        # Inject the re-encoded packet back through the inbound queue so
        # ApplyRemotePacketUseCase processes it like any other arrival.
        try:
            data = self._codec.encode(packet)
        except Exception:
            return
        if self._on_resend_recv is not None:
            self._on_resend_recv(data)

    def set_resend_receiver(self, fn) -> None:
        """Runtime injects a callable to feed RESEND payloads into the
        inbound queue (so the chain verifier sees them)."""
        self._on_resend_recv = fn

    _on_resend_recv = None  # type: ignore[assignment]

    def _send_control(self, ops: list[dict]) -> None:
        packet = self._builder.build(
            CategoryKind.CONTROL, ops, self._clock.now(),
        )
        try:
            data = self._codec.encode(packet)
        except Exception:
            return
        self._async_runner.run_coroutine(
            self._transport.send(packet.channel, data)
        )

    def send_ping(self) -> None:
        op = {
            "type": ControlOpKind.PING.value,
            "t": self._clock.monotonic(),
        }
        self._send_control([op])

    def send_nack(self, author: str, first: int, last: int) -> None:
        op = {
            "type": ControlOpKind.NACK.value,
            "author": author,
            "from": int(first),
            "to": int(last),
        }
        self._send_control([op])

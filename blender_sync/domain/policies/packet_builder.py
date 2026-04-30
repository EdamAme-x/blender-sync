from __future__ import annotations

import json
from collections import deque
from typing import Any

from ..entities import CATEGORY_TO_CHANNEL, CategoryKind, ChannelKind, Packet
from .packet_chain import PacketChain


class SeqCounter:
    def __init__(self, start: int = 0) -> None:
        self._value = start

    def next(self) -> int:
        self._value += 1
        return self._value

    @property
    def current(self) -> int:
        return self._value


def _packet_body_for_chain(packet_dict: dict[str, Any]) -> bytes:
    """Stable byte representation used for the rolling chain. Must match
    on sender and receiver, so we use sorted-key JSON of the wire dict
    minus the chain fields themselves (chicken-and-egg)."""
    cleaned = {k: v for k, v in packet_dict.items() if k not in ("c", "d")}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


class PacketBuilder:
    """Constructs Packets and maintains the per-peer outgoing chain.

    The chain only advances for RELIABLE packets — fast/transform packets
    are unordered + lossy by design and excluded from the verification
    protocol.
    """

    def __init__(self, peer_id: str, seq: SeqCounter, version: int = 1) -> None:
        self._peer_id = peer_id
        self._seq = seq
        self._version = version
        self._chain = PacketChain()

    @property
    def chain_state(self) -> PacketChain:
        return self._chain

    def build(
        self,
        category: CategoryKind,
        ops: list[dict[str, Any]],
        ts: float,
        force: bool = False,
    ) -> Packet:
        seq = self._seq.next()
        skeleton = Packet(
            version=self._version,
            seq=seq,
            ts=ts,
            author=self._peer_id,
            category=category,
            ops=tuple(ops),
            force=force,
        )
        if CATEGORY_TO_CHANNEL[category] is not ChannelKind.RELIABLE:
            return skeleton
        body = _packet_body_for_chain(skeleton.to_wire_dict())
        a, b = self._chain.advance(body)
        chain_value = (b << 16) | a
        return Packet(
            version=self._version,
            seq=seq,
            ts=ts,
            author=self._peer_id,
            category=category,
            ops=tuple(ops),
            force=force,
            chain=chain_value,
            digit=chain_value % 10,
        )


class OutboundHistory:
    """Ring buffer of recently-sent reliable packets.

    On NACK we look up packets by seq and re-encode/send them. Capacity
    is bounded so memory doesn't grow unbounded; if a peer falls so far
    behind that the gap is older than `capacity`, the only recovery is
    a Force Pull (full snapshot).
    """

    def __init__(self, capacity: int = 256) -> None:
        self._buf: deque[Packet] = deque(maxlen=capacity)
        self._capacity = capacity

    @property
    def capacity(self) -> int:
        return self._capacity

    def record(self, packet: Packet) -> None:
        if packet.chain == 0:
            # Fast/unreliable packets are not retransmittable.
            return
        self._buf.append(packet)

    def get(self, seq: int) -> Packet | None:
        for p in self._buf:
            if p.seq == seq:
                return p
        return None

    def range(self, first: int, last: int) -> list[Packet]:
        return [p for p in self._buf if first <= p.seq <= last]

    def oldest_seq(self) -> int | None:
        if not self._buf:
            return None
        return self._buf[0].seq


def lww_key(category: CategoryKind, op: dict[str, Any]) -> str:
    if category is CategoryKind.TRANSFORM:
        return f"transform:{op.get('n', '')}"
    if category is CategoryKind.MATERIAL:
        return f"material:{op.get('mat', '')}"
    if category is CategoryKind.MODIFIER:
        return f"modifier:{op.get('obj', '')}"
    if category is CategoryKind.MESH:
        return f"mesh:{op.get('obj', '')}"
    if category is CategoryKind.VISIBILITY:
        return f"visibility:{op.get('n', '')}"
    if category is CategoryKind.RENDER:
        return "render:scene"
    if category is CategoryKind.COMPOSITOR:
        return "compositor:scene"
    if category is CategoryKind.SCENE:
        return "scene:world"
    return f"{category.value}:misc"

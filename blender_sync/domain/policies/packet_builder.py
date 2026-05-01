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
    """Per-op LWW key.

    Each op carries some natural identifier (object name, material name,
    datablock name, owner+kind for deletion / rename, etc.). LWW must
    key by *that* identifier so two ops in the same packet for two
    distinct datablocks don't share a key — otherwise the second op
    looks like a duplicate of the first and is rejected.

    Singletons (compositor, render, scene world, view3d) legitimately
    share a key across the category — they only ever carry one op per
    packet.
    """
    # Object-side ops keyed by Object name (`n` for transform/visibility,
    # `obj` for everything that hangs off an Object).
    if category is CategoryKind.TRANSFORM:
        return f"transform:{op.get('n', '')}"
    if category is CategoryKind.VISIBILITY:
        return f"visibility:{op.get('n', '')}"
    if category is CategoryKind.MODIFIER:
        return f"modifier:{op.get('obj', '')}"
    if category is CategoryKind.MATERIAL_SLOTS:
        return f"material_slots:{op.get('obj', '')}"
    if category is CategoryKind.MESH:
        return f"mesh:{op.get('obj', '')}"
    if category is CategoryKind.POSE:
        return f"pose:{op.get('obj', '')}"
    if category is CategoryKind.SHAPE_KEYS:
        return f"shape_keys:{op.get('obj', '')}"
    if category is CategoryKind.CONSTRAINTS:
        return f"constraints:{op.get('obj', '')}"
    if category is CategoryKind.PARTICLE:
        return f"particle:{op.get('obj', '')}"

    # Material datablock: keyed by mat name.
    if category is CategoryKind.MATERIAL:
        return f"material:{op.get('mat', '')}"

    # Deletion / Rename: identified by (kind, name) and (kind, uid).
    # Without per-op keys here, a packet that deletes 5 datablocks would
    # only delete the first one because the rest would look like
    # duplicates of the same LWW slot.
    if category is CategoryKind.DELETION:
        return f"deletion:{op.get('kind', '')}:{op.get('name', '')}"
    if category is CategoryKind.RENAME:
        return f"rename:{op.get('kind', '')}:{op.get('uid', '')}"

    # Animation owners: each fanned-out owner gets its own key.
    if category is CategoryKind.ANIMATION:
        return (
            f"animation:{op.get('owner_type', 'object')}"
            f":{op.get('owner', '')}"
        )

    # VSE strip ops are per-scene (one op per Scene that has a VSE).
    if category is CategoryKind.VSE_STRIP:
        return f"vse_strip:{op.get('scene', '')}"

    # Datablock-level singletons keyed by `name`.
    if category in (
        CategoryKind.IMAGE, CategoryKind.TEXTURE, CategoryKind.NODE_GROUP,
        CategoryKind.ARMATURE,
        CategoryKind.CAMERA, CategoryKind.LIGHT, CategoryKind.COLLECTION,
        CategoryKind.GREASE_PENCIL, CategoryKind.CURVE,
        CategoryKind.LATTICE, CategoryKind.METABALL,
        CategoryKind.VOLUME, CategoryKind.POINT_CLOUD,
        CategoryKind.SOUND,
    ):
        return f"{category.value}:{op.get('name', '')}"

    # True singletons — only ever one op per packet.
    if category is CategoryKind.RENDER:
        return "render:scene"
    if category is CategoryKind.COMPOSITOR:
        return "compositor:scene"
    if category is CategoryKind.SCENE:
        return "scene:world"
    if category is CategoryKind.VIEW3D:
        return "view3d:active"

    return f"{category.value}:misc"

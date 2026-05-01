"""Regression tests for the chain-skip wedge bug (codex P1-1 + P1-8).

P1-1: a burst of fast / force packets used to wedge the receiver
because they shared the seq counter with reliable packets.

P1-1's first fix advanced `expected_seq` past skipped packets, which
P1-8 then proved buggy in the reverse direction: a delayed reliable
packet could arrive after a fast packet had already pulled
`expected_seq` past it, and would be silently held back forever.

The proper fix (P1-8): PacketBuilder maintains two independent seq
counters — one for reliable+chain-verified packets, one for fast /
unreliable packets. Receiver only ever tracks the reliable counter.
chain==0 (fast) packets are accepted unconditionally and don't touch
expected_seq. force=True packets stay on the reliable chain (they
come on the reliable channel) so NACK/RESEND keeps working past a
Force Push.

These tests verify both directions: a burst of fast packets does not
cause a wedge, and a delayed reliable packet that arrives after a
fast packet still applies.
"""
from __future__ import annotations

import json

from blender_sync.domain.entities import CategoryKind, Packet, SyncConfig
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.domain.policies.packet_chain import PacketChain
from blender_sync.usecases.apply_remote import ApplyRemotePacketUseCase
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway


class _SimpleCodec:
    def __init__(self) -> None:
        self._packets: dict[bytes, Packet] = {}

    def encode(self, packet: Packet) -> bytes:
        key = id(packet).to_bytes(8, "little")
        self._packets[key] = packet
        return key

    def decode(self, data: bytes) -> Packet:
        return self._packets[data]


def _make_uc():
    scene = FakeSceneGateway()
    codec = _SimpleCodec()
    echo = EchoFilter(self_peer_id="me")
    lww = LWWResolver()
    logger = RecordingLogger()
    cfg = SyncConfig(peer_id="me")
    uc = ApplyRemotePacketUseCase(scene, codec, echo, lww, logger, cfg)
    return uc, scene, codec, logger


def _packet_body_for_chain(packet: Packet) -> bytes:
    d = packet.to_wire_dict()
    cleaned = {k: v for k, v in d.items() if k not in ("c", "d")}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _build_reliable(seq: int, ts: float, ops, chain: PacketChain,
                    category=CategoryKind.MATERIAL,
                    author: str = "alice",
                    force: bool = False) -> Packet:
    """Build a reliable packet whose chain field is correctly computed
    against the supplied PacketChain. Mutates `chain` to advance it,
    matching what PacketBuilder does on the sender side.

    Pass `force=True` to compute the chain over the force-flag wire
    representation so receiver chain verification matches."""
    skel = Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=category, ops=tuple(ops), force=force,
    )
    body = _packet_body_for_chain(skel)
    a, b = chain.advance(body)
    val = (b << 16) | a
    return Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=category, ops=tuple(ops),
        force=force,
        chain=val, digit=val % 10,
    )


def _build_fast(seq: int, ts: float, ops, author: str = "alice") -> Packet:
    """Build a fast/transform packet (chain=0, skipped on receiver)."""
    return Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=CategoryKind.TRANSFORM,
        ops=tuple(ops),
    )


def _build_force(seq: int, ts: float, ops, chain: PacketChain,
                 author: str = "alice",
                 category=CategoryKind.MATERIAL) -> Packet:
    """Build a force packet — rides the reliable chain (P1-8 fix)."""
    return _build_reliable(seq, ts, ops, chain,
                           category=category, author=author, force=True)


# ----------------------------------------------------------------------
# Wedge regression: fast packets between reliable packets
# ----------------------------------------------------------------------

def test_fast_packets_then_reliable_apply_without_wedge():
    """Reliable seq=1 follows two fast packets. Receiver must accept
    all three, fast packets don't touch expected_seq."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()

    nacks: list = []
    uc.set_nack_emitter(lambda author, first, last: nacks.append((author, first, last)))

    # Fast packets ride a separate seq counter; their seqs (1, 2) live
    # in a different namespace from reliable seq.
    fast_a = _build_fast(1, 1.0, [{"n": "Cube", "loc": [0, 0, 0]}])
    fast_b = _build_fast(2, 2.0, [{"n": "Cube", "loc": [1, 0, 0]}])
    # Reliable counter starts at 1.
    rel1 = _build_reliable(1, 3.0,
                           [{"mat": "Material", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(fast_a))
    uc.apply_raw(codec.encode(fast_b))
    uc.apply_raw(codec.encode(rel1))

    assert len(scene.applied) == 3
    cats = [c for c, _ in scene.applied]
    assert cats == [CategoryKind.TRANSFORM, CategoryKind.TRANSFORM,
                    CategoryKind.MATERIAL]
    assert nacks == []


def test_force_packet_remains_on_reliable_chain():
    """Force packet rides the reliable seq+chain. Receiver applies it
    normally and the next reliable packet is NOT a gap."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()

    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    # Force packets carry a real chain because they ride the reliable
    # channel.
    force1 = _build_force(1, 1.0,
                          [{"mat": "Mat", "use_nodes": True}], chain)
    rel2 = _build_reliable(2, 2.0,
                           [{"mat": "Mat2", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(force1))
    uc.apply_raw(codec.encode(rel2))

    assert len(scene.applied) == 2
    assert nacks == []


def test_long_fast_burst_does_not_wedge():
    """100 fast packets followed by reliable seq=1: must apply, no NACK."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    for i in range(1, 101):
        fast = _build_fast(i, float(i), [{"n": "Cube"}])
        uc.apply_raw(codec.encode(fast))
    rel = _build_reliable(1, 101.0,
                          [{"mat": "M", "use_nodes": True}], chain)
    uc.apply_raw(codec.encode(rel))

    assert len(scene.applied) == 101
    assert nacks == []


def test_late_reliable_after_fast_still_applies():
    """The exact P1-8 regression: reliable seq=1 arrives AFTER fast
    seq=1 (independent counter, but pre-P1-8 the shared counter would
    have made the receiver drop it). Reliable must still apply."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    fast1 = _build_fast(1, 1.0, [{"n": "Cube"}])
    rel1 = _build_reliable(1, 2.0,
                           [{"mat": "M", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(fast1))
    uc.apply_raw(codec.encode(rel1))

    assert len(scene.applied) == 2
    assert nacks == []


def test_held_back_reliable_drains_after_fast_skip():
    """Out-of-order reliable arrival with a fast in between."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    fast_a = _build_fast(1, 1.0, [{"n": "Cube"}])
    rel1 = _build_reliable(1, 2.0,
                           [{"mat": "A", "use_nodes": True}], chain)
    rel2 = _build_reliable(2, 3.0,
                           [{"mat": "B", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(fast_a))
    uc.apply_raw(codec.encode(rel2))   # held back, NACK 1..1
    assert nacks == [("alice", 1, 1)]
    assert len(scene.applied) == 1   # only fast so far

    uc.apply_raw(codec.encode(rel1))
    assert len(scene.applied) == 3
    cats = [c for c, _ in scene.applied]
    assert cats == [CategoryKind.TRANSFORM,
                    CategoryKind.MATERIAL,
                    CategoryKind.MATERIAL]


def test_chain_continuity_preserved_across_fast_skip():
    """Sender chain advances only on reliable. Receiver chain stays
    contiguous on reliable seq=2 even with fast packets in between."""
    uc, scene, codec, _ = _make_uc()
    sender_chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    rel1 = _build_reliable(1, 1.0,
                           [{"mat": "A", "use_nodes": True}], sender_chain)
    fast_a = _build_fast(1, 2.0, [{"n": "Cube"}])
    fast_b = _build_fast(2, 3.0, [{"n": "Cube"}])
    rel2 = _build_reliable(2, 4.0,
                           [{"mat": "B", "use_nodes": True}], sender_chain)

    uc.apply_raw(codec.encode(rel1))
    uc.apply_raw(codec.encode(fast_a))
    uc.apply_raw(codec.encode(fast_b))
    uc.apply_raw(codec.encode(rel2))

    assert len(scene.applied) == 4
    assert nacks == []


def test_duplicate_after_fast_is_still_dropped():
    """A retransmit / duplicate reliable seq must still be discarded."""
    uc, scene, codec, _ = _make_uc()
    sender_chain = PacketChain()

    rel1 = _build_reliable(1, 1.0,
                           [{"mat": "A", "use_nodes": True}], sender_chain)
    uc.apply_raw(codec.encode(rel1))
    fast_a = _build_fast(1, 2.0, [{"n": "Cube"}])
    uc.apply_raw(codec.encode(fast_a))

    uc.apply_raw(codec.encode(rel1))
    assert len(scene.applied) == 2  # rel1, fast — not 3.


def test_fast_packet_does_not_advance_expected_seq():
    """The core P1-8 invariant: chain==0 packets must not touch
    expected_seq. The receiver doesn't even instantiate per-author
    chain state for them — fast packets are accepted unconditionally
    and never interact with reliable seq tracking."""
    uc, scene, codec, _ = _make_uc()
    fast1 = _build_fast(1, 1.0, [{"n": "Cube"}])
    fast2 = _build_fast(2, 2.0, [{"n": "Cube"}])
    uc.apply_raw(codec.encode(fast1))
    uc.apply_raw(codec.encode(fast2))

    # No per-author chain state required for fast-only authors.
    assert "alice" not in uc._chains
    # Both fast packets applied.
    assert len(scene.applied) == 2

    # Once a real reliable packet arrives, the chain state should
    # initialize at expected_seq=1 — i.e., the fast packets did not
    # secretly bump the reliable counter.
    chain = PacketChain()
    rel1 = _build_reliable(1, 3.0,
                           [{"mat": "M", "use_nodes": True}], chain)
    uc.apply_raw(codec.encode(rel1))
    state = uc._chains["alice"]
    assert state.last_verified_seq == 1
    assert state.expected_seq == 2

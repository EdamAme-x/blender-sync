"""Regression tests for the chain-skip wedge bug (codex P1-1).

The bug: PacketBuilder uses a single SeqCounter for *all* outgoing
packets (reliable + fast + force). The receiver's `expected_seq` was
only advanced for in-order *reliable* packets, so a burst of fast
(transform / view3d / pose) packets between reliable packets caused
the next reliable packet to look like a gap. NACK was then emitted
for seqs that the sender's reliable history doesn't contain (chain==0
or force=True), which produces a permanent stall — wedge.

Fix in apply_remote.py: when we see a chain==0 or force packet whose
seq is >= our expected_seq, advance expected_seq past it. The chain
itself (last_verified_seq, rolling A/B) is intentionally NOT touched —
those skipped packets aren't part of the verified chain.
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
                    author: str = "alice") -> Packet:
    """Build a reliable packet whose chain field is correctly computed
    against the supplied PacketChain. Mutates `chain` to advance it,
    matching what PacketBuilder does on the sender side."""
    skel = Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=category, ops=tuple(ops),
    )
    body = _packet_body_for_chain(skel)
    a, b = chain.advance(body)
    val = (b << 16) | a
    return Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=category, ops=tuple(ops),
        chain=val, digit=val % 10,
    )


def _build_fast(seq: int, ts: float, ops, author: str = "alice") -> Packet:
    """Build a fast/transform packet (chain=0, skipped on receiver)."""
    return Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=CategoryKind.TRANSFORM,
        ops=tuple(ops),
    )


def _build_force(seq: int, ts: float, ops, author: str = "alice",
                 category=CategoryKind.MATERIAL) -> Packet:
    """Build a force packet — chain stays 0, force=True."""
    return Packet(
        version=1, seq=seq, ts=ts, author=author,
        category=category, ops=tuple(ops),
        force=True,
    )


# ----------------------------------------------------------------------
# Wedge regression: fast packets between reliable packets
# ----------------------------------------------------------------------

def test_fast_packets_advance_expected_seq_for_next_reliable():
    """Sender sends seq=1 fast, seq=2 fast, seq=3 reliable. Receiver
    must accept all three without NACK."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()

    nacks: list = []
    uc.set_nack_emitter(lambda author, first, last: nacks.append((author, first, last)))

    fast1 = _build_fast(1, 1.0, [{"n": "Cube", "loc": [0, 0, 0]}])
    fast2 = _build_fast(2, 2.0, [{"n": "Cube", "loc": [1, 0, 0]}])
    # The sender's chain is unaffected by fast packets, so seq=3
    # reliable starts the chain at fresh A=1 B=0.
    rel3 = _build_reliable(3, 3.0,
                            [{"mat": "Material", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(fast1))
    uc.apply_raw(codec.encode(fast2))
    uc.apply_raw(codec.encode(rel3))

    # Three packets applied (2 fast transforms + 1 reliable material).
    assert len(scene.applied) == 3
    cats = [c for c, _ in scene.applied]
    assert cats[0] is CategoryKind.TRANSFORM
    assert cats[1] is CategoryKind.TRANSFORM
    assert cats[2] is CategoryKind.MATERIAL
    # No NACK — pre-fix this would emit one for seqs 1..2.
    assert nacks == []


def test_force_packet_advances_expected_seq():
    """Force-push (chain=0, force=True) consumes seq. Subsequent reliable
    packet must not be misidentified as a gap."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()

    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    force1 = _build_force(1, 1.0, [{"mat": "Mat", "use_nodes": True}])
    rel2 = _build_reliable(2, 2.0,
                           [{"mat": "Mat2", "use_nodes": True}], chain)

    uc.apply_raw(codec.encode(force1))
    uc.apply_raw(codec.encode(rel2))

    assert len(scene.applied) == 2
    assert nacks == []


def test_long_fast_burst_does_not_wedge():
    """100 fast packets followed by 1 reliable packet — the previous
    bug would NACK seqs 1..100 and stall."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    for i in range(1, 101):
        fast = _build_fast(i, float(i), [{"n": "Cube"}])
        uc.apply_raw(codec.encode(fast))
    rel = _build_reliable(101, 101.0,
                          [{"mat": "M", "use_nodes": True}], chain)
    uc.apply_raw(codec.encode(rel))

    assert len(scene.applied) == 101
    assert nacks == []


def test_held_back_reliable_drains_after_fast_skip():
    """Out-of-order arrival: reliable seq=3 arrives before reliable
    seq=2, with a fast seq=1 in between. After the fast skip + reliable
    seq=2 arrives, both should be applied without NACK."""
    uc, scene, codec, _ = _make_uc()
    chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    fast1 = _build_fast(1, 1.0, [{"n": "Cube"}])
    rel2 = _build_reliable(2, 2.0,
                           [{"mat": "A", "use_nodes": True}], chain)
    rel3 = _build_reliable(3, 3.0,
                           [{"mat": "B", "use_nodes": True}], chain)

    # Order: fast1, then rel3 first (out of order), then rel2.
    uc.apply_raw(codec.encode(fast1))
    uc.apply_raw(codec.encode(rel3))   # held back, NACK 2..2 expected
    assert nacks == [("alice", 2, 2)]
    assert len(scene.applied) == 1   # only fast1 so far

    uc.apply_raw(codec.encode(rel2))  # in-order; drains rel3 too
    assert len(scene.applied) == 3
    cats = [c for c, _ in scene.applied]
    assert cats == [CategoryKind.TRANSFORM,
                    CategoryKind.MATERIAL,
                    CategoryKind.MATERIAL]


def test_chain_continuity_preserved_across_fast_skip():
    """The reliable chain must remain contiguous on the receiver side
    after fast packets in between. Sender's chain advances only on
    reliable packets, so receiver's chain after seq=4 reliable should
    match the sender's seq=4 reliable chain value."""
    uc, scene, codec, _ = _make_uc()
    sender_chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    rel1 = _build_reliable(1, 1.0,
                           [{"mat": "A", "use_nodes": True}], sender_chain)
    fast2 = _build_fast(2, 2.0, [{"n": "Cube"}])
    fast3 = _build_fast(3, 3.0, [{"n": "Cube"}])
    rel4 = _build_reliable(4, 4.0,
                           [{"mat": "B", "use_nodes": True}], sender_chain)

    uc.apply_raw(codec.encode(rel1))
    uc.apply_raw(codec.encode(fast2))
    uc.apply_raw(codec.encode(fast3))
    uc.apply_raw(codec.encode(rel4))

    assert len(scene.applied) == 4
    assert nacks == []


def test_duplicate_after_fast_skip_is_still_dropped():
    """A retransmit / duplicate of an already-verified reliable packet
    must still be discarded after fast packets advanced expected_seq."""
    uc, scene, codec, _ = _make_uc()
    sender_chain = PacketChain()

    rel1 = _build_reliable(1, 1.0,
                           [{"mat": "A", "use_nodes": True}], sender_chain)
    uc.apply_raw(codec.encode(rel1))
    fast2 = _build_fast(2, 2.0, [{"n": "Cube"}])
    uc.apply_raw(codec.encode(fast2))

    # Re-deliver the same rel1 packet (e.g. because of NACK echo).
    uc.apply_raw(codec.encode(rel1))
    # Should not double-apply.
    assert len(scene.applied) == 2  # rel1, fast2 only.


def test_force_packet_does_not_break_subsequent_chain_verification():
    """After a Force Push (force=True, chain=0) sender's reliable chain
    might also be reset (Force Pull resets receiver's chain explicitly).
    Here we only test that a follow-up reliable packet is not NACKed
    spuriously."""
    uc, scene, codec, _ = _make_uc()
    sender_chain = PacketChain()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    force1 = _build_force(1, 1.0, [{"mat": "A", "use_nodes": True}])
    rel2 = _build_reliable(2, 2.0,
                           [{"mat": "B", "use_nodes": True}], sender_chain)
    uc.apply_raw(codec.encode(force1))
    uc.apply_raw(codec.encode(rel2))

    assert len(scene.applied) == 2
    assert nacks == []


def test_chain_skip_does_not_advance_last_verified_seq():
    """`last_verified_seq` (used by `is_duplicate`) tracks reliable-only
    progress. A fast packet must not bump it, otherwise a delayed
    reliable packet at that seq would be wrongly flagged as duplicate."""
    uc, scene, codec, _ = _make_uc()
    fast1 = _build_fast(1, 1.0, [{"n": "Cube"}])
    uc.apply_raw(codec.encode(fast1))

    state = uc._chains["alice"]
    # expected_seq advanced past the fast packet.
    assert state.expected_seq == 2
    # But last_verified_seq stayed at the initial value (0). Otherwise
    # a duplicate-check on seq=1 reliable would incorrectly succeed.
    assert state.last_verified_seq == 0

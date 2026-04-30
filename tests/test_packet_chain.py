"""Tests for the rolling-checksum chain + NACK/RESEND recovery protocol."""
from __future__ import annotations

import json

from blender_sync.domain.entities import (
    CategoryKind,
    ChannelKind,
    Packet,
    SyncConfig,
)
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.domain.policies.packet_builder import (
    OutboundHistory,
    PacketBuilder,
    SeqCounter,
)
from blender_sync.domain.policies.packet_chain import (
    PacketChain,
    fold,
    step,
)
from blender_sync.usecases.apply_remote import ApplyRemotePacketUseCase
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway


class _JsonCodec:
    def encode(self, packet):
        return json.dumps(packet.to_wire_dict(), sort_keys=True).encode("utf-8")

    def decode(self, data):
        return Packet.from_wire_dict(json.loads(data.decode("utf-8")))


# === Pure chain math ===


def test_chain_step_is_deterministic():
    a, b = step(1, 0, b"abc")
    assert step(1, 0, b"abc") == (a, b)


def test_chain_step_is_sensitive_to_content():
    a1, b1 = step(1, 0, b"abc")
    a2, b2 = step(1, 0, b"abd")
    assert (a1, b1) != (a2, b2)


def test_chain_step_is_sensitive_to_order():
    a1, b1 = step(*step(1, 0, b"a"), b"b")
    a2, b2 = step(*step(1, 0, b"b"), b"a")
    assert (a1, b1) != (a2, b2)


def test_chain_advance_matches_step():
    pc = PacketChain()
    pc.advance(b"x")
    pc.advance(b"y")
    a, b = step(*step(1, 0, b"x"), b"y")
    assert (pc.a, pc.b) == (a, b)
    assert pc.chain == fold(a, b)


# === PacketBuilder integration ===


def test_packet_builder_sets_chain_for_reliable():
    b = PacketBuilder("me", SeqCounter())
    p1 = b.build(CategoryKind.MATERIAL, [{"mat": "M"}], 1.0)
    assert p1.chain != 0
    assert p1.digit == p1.chain % 10


def test_packet_builder_skips_chain_for_fast():
    b = PacketBuilder("me", SeqCounter())
    p = b.build(CategoryKind.TRANSFORM, [{"n": "Cube"}], 1.0)
    assert p.channel is ChannelKind.FAST
    assert p.chain == 0
    assert p.digit == 0


def test_chain_advances_monotonically():
    b = PacketBuilder("me", SeqCounter())
    p1 = b.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0)
    p2 = b.build(CategoryKind.MATERIAL, [{"mat": "B"}], 2.0)
    assert p1.chain != p2.chain


def test_force_packet_still_chained():
    b = PacketBuilder("me", SeqCounter())
    p = b.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0, force=True)
    assert p.force is True
    assert p.chain != 0


# === OutboundHistory ===


def test_history_records_only_reliable():
    hist = OutboundHistory(capacity=10)
    b = PacketBuilder("me", SeqCounter())
    fast = b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 1.0)
    reliable = b.build(CategoryKind.MATERIAL, [{"mat": "M"}], 1.0)
    hist.record(fast)
    hist.record(reliable)
    assert hist.get(fast.seq) is None
    assert hist.get(reliable.seq) is reliable


def test_history_drops_oldest_at_capacity():
    hist = OutboundHistory(capacity=3)
    b = PacketBuilder("me", SeqCounter())
    pkts = [b.build(CategoryKind.MATERIAL, [{"i": i}], float(i))
            for i in range(5)]
    for p in pkts:
        hist.record(p)
    assert hist.get(pkts[0].seq) is None
    assert hist.get(pkts[1].seq) is None
    assert hist.get(pkts[4].seq) is pkts[4]
    assert hist.oldest_seq() == pkts[2].seq


def test_history_range_returns_packets():
    hist = OutboundHistory()
    b = PacketBuilder("me", SeqCounter())
    pkts = [b.build(CategoryKind.MATERIAL, [{"i": i}], 1.0) for i in range(5)]
    for p in pkts:
        hist.record(p)
    got = hist.range(pkts[1].seq, pkts[3].seq)
    assert [p.seq for p in got] == [pkts[1].seq, pkts[2].seq, pkts[3].seq]


# === ApplyRemotePacketUseCase chain verification ===


def _make_uc():
    scene = FakeSceneGateway()
    codec = _JsonCodec()
    echo = EchoFilter(self_peer_id="me")
    lww = LWWResolver()
    cfg = SyncConfig(peer_id="me")
    uc = ApplyRemotePacketUseCase(scene, codec, echo, lww, RecordingLogger(), cfg)
    return uc, scene, codec


def test_in_order_reliable_packets_apply():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    nacks: list[tuple[str, int, int]] = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "M1"}], 1.0)
    p2 = builder.build(CategoryKind.MATERIAL, [{"mat": "M2"}], 2.0)
    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p2))

    assert len(scene.applied) == 2
    assert nacks == []


def test_gap_triggers_nack_and_holds_packet():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    nacks: list[tuple[str, int, int]] = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "M1"}], 1.0)
    p2 = builder.build(CategoryKind.MATERIAL, [{"mat": "M2"}], 2.0)
    p3 = builder.build(CategoryKind.MATERIAL, [{"mat": "M3"}], 3.0)

    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p3))  # skip p2

    assert len(scene.applied) == 1  # only p1 applied
    assert nacks == [("alice", p2.seq, p2.seq)]


def test_resend_fills_gap_and_drains_held_back():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    nacks: list[tuple[str, int, int]] = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "M1"}], 1.0)
    p2 = builder.build(CategoryKind.MATERIAL, [{"mat": "M2"}], 2.0)
    p3 = builder.build(CategoryKind.MATERIAL, [{"mat": "M3"}], 3.0)

    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p3))  # held
    assert len(scene.applied) == 1

    uc.apply_raw(codec.encode(p2))  # fills gap, p3 drains
    assert len(scene.applied) == 3
    assert [op[0] for op in scene.applied] == [
        CategoryKind.MATERIAL, CategoryKind.MATERIAL, CategoryKind.MATERIAL,
    ]


def test_duplicate_resend_after_gap_filled_is_ignored():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    uc.set_nack_emitter(lambda a, f, l: None)

    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "M1"}], 1.0)
    p2 = builder.build(CategoryKind.MATERIAL, [{"mat": "M2"}], 2.0)
    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p2))
    uc.apply_raw(codec.encode(p1))  # duplicate

    assert len(scene.applied) == 2


def test_fast_packets_bypass_chain():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    nacks: list[tuple[str, int, int]] = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    p1 = builder.build(CategoryKind.TRANSFORM, [{"n": "C"}], 1.0)
    p2 = builder.build(CategoryKind.TRANSFORM, [{"n": "C"}], 2.0)
    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p2))

    assert len(scene.applied) == 2
    assert nacks == []  # transform never NACKs


def test_force_packet_bypasses_chain():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    uc.set_nack_emitter(lambda a, f, l: None)

    # First a normal reliable packet to seed the chain.
    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0)
    # Then a force packet that arrives even if the chain were stale.
    p_force = builder.build(CategoryKind.MATERIAL, [{"mat": "B"}], 2.0, force=True)

    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p_force))
    assert len(scene.applied) == 2


def test_corrupted_chain_triggers_recovery():
    uc, scene, codec = _make_uc()
    builder = PacketBuilder("alice", SeqCounter())
    nacks: list[tuple[str, int, int]] = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    p1 = builder.build(CategoryKind.MATERIAL, [{"mat": "M1"}], 1.0)
    # Manually corrupt the chain digit but keep seq in-order.
    bad = Packet(
        version=p1.version, seq=p1.seq, ts=p1.ts, author=p1.author,
        category=p1.category, ops=p1.ops, chain=99999, digit=9,
    )
    uc.apply_raw(codec.encode(bad))

    assert nacks == [("alice", p1.seq, p1.seq)]
    assert scene.applied == []

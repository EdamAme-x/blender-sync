"""Regression tests for P1-8: PacketBuilder reliable / unreliable seq split.

History:
- The original PacketBuilder shared a single SeqCounter across all
  outgoing packets (reliable + fast + force).
- P1-1's fix advanced `expected_seq` past skipped packets on the
  receiver to avoid wedge.
- Codex follow-up review caught that this opened a reverse bug: a
  fast packet arriving before a slow reliable packet would push
  `expected_seq` past the seq the reliable packet eventually arrived
  with, causing it to be silently held back forever.

The proper fix (P1-8) is structural: reliable and fast packets ride
independent seq counters. Force packets stay on the reliable chain
because they need NACK/RESEND continuity past a Force Push.

These tests cover the contract:
  * fast packets advance only the unreliable counter
  * reliable + force packets advance the reliable counter and chain
  * the two streams have non-overlapping seq spaces in the typical
    (small) case — both can start at 1 simultaneously
"""
from __future__ import annotations

from blender_sync.domain.entities import CategoryKind, ChannelKind
from blender_sync.domain.policies.packet_builder import (
    PacketBuilder,
    SeqCounter,
)


def test_reliable_seq_counter_only_advances_for_reliable_packets():
    seq = SeqCounter()
    b = PacketBuilder("me", seq=seq)
    fast1 = b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 1.0)
    fast2 = b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 2.0)
    rel1 = b.build(CategoryKind.MATERIAL, [{"mat": "M"}], 3.0)
    # The reliable counter must be 1 after the only reliable build.
    assert seq.current == 1
    assert rel1.seq == 1
    # Fast packets used the independent counter, both starting at 1.
    assert fast1.seq == 1
    assert fast2.seq == 2


def test_fast_packets_have_no_chain():
    b = PacketBuilder("me", seq=SeqCounter())
    p = b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 1.0)
    assert p.chain == 0
    assert p.digit == 0
    assert p.force is False


def test_reliable_packets_carry_chain():
    b = PacketBuilder("me", seq=SeqCounter())
    p = b.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0)
    assert p.chain != 0
    assert p.digit == p.chain % 10


def test_force_packet_stays_on_reliable_chain_with_chain_value():
    """P1-8: force packets are NOT shunted to the unreliable counter
    anymore — they stay on the reliable counter so NACK/RESEND keeps
    working past a Force Push."""
    seq = SeqCounter()
    b = PacketBuilder("me", seq=seq)
    f = b.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0, force=True)
    assert f.force is True
    # Force packet on the reliable chain → non-zero chain value.
    assert f.chain != 0
    # And it consumed the reliable counter (=1).
    assert seq.current == 1
    assert f.seq == 1


def test_fast_then_reliable_seqs_can_collide():
    """The whole point of the split: reliable seq=1 and fast seq=1 can
    coexist on the wire. Receiver tells them apart by chain == 0."""
    b = PacketBuilder("me", seq=SeqCounter())
    fast = b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 1.0)
    rel = b.build(CategoryKind.MATERIAL, [{"mat": "M"}], 2.0)
    assert fast.seq == 1
    assert rel.seq == 1
    assert fast.chain == 0
    assert rel.chain != 0


def test_fast_burst_does_not_advance_reliable_counter():
    seq = SeqCounter()
    b = PacketBuilder("me", seq=seq)
    for i in range(50):
        b.build(CategoryKind.TRANSFORM, [{"n": "X"}], float(i))
    assert seq.current == 0  # never touched
    rel = b.build(CategoryKind.MATERIAL, [{"mat": "M"}], 100.0)
    assert rel.seq == 1
    assert seq.current == 1


def test_unreliable_seq_counter_can_be_injected_for_isolation():
    """Tests / future runtime can inject an unreliable counter; default
    is a fresh SeqCounter()."""
    rel_seq = SeqCounter()
    fast_seq = SeqCounter()
    b = PacketBuilder("me", seq=rel_seq, unreliable_seq=fast_seq)
    for _ in range(3):
        b.build(CategoryKind.TRANSFORM, [{"n": "X"}], 1.0)
    assert rel_seq.current == 0
    assert fast_seq.current == 3


def test_chain_continuity_only_reliable():
    """5 reliable packets interleaved with 5 fast packets: reliable
    chain still increments contiguously."""
    b = PacketBuilder("me", seq=SeqCounter())
    rels = []
    for i in range(5):
        b.build(CategoryKind.TRANSFORM, [{"n": "X"}], float(i))
        r = b.build(CategoryKind.MATERIAL, [{"mat": f"M{i}"}], float(i))
        rels.append(r)
    # All reliable seq strictly increasing 1..5.
    assert [r.seq for r in rels] == [1, 2, 3, 4, 5]
    # Each chain value is unique (Adler is sensitive to seq + content).
    chains = {r.chain for r in rels}
    assert len(chains) == 5


def test_view3d_pose_categories_use_unreliable_seq():
    """Sanity: every FAST-channel category must go through the
    unreliable counter. View3D and Pose were both added in PR #10."""
    seq = SeqCounter()
    b = PacketBuilder("me", seq=seq)
    p_view3d = b.build(CategoryKind.VIEW3D, [{}], 1.0)
    p_pose = b.build(CategoryKind.POSE, [{"obj": "Arm"}], 2.0)
    assert p_view3d.chain == 0
    assert p_pose.chain == 0
    # Reliable counter never moved.
    assert seq.current == 0


def test_categories_match_channel_table():
    """Every category in the project goes through PacketBuilder.build,
    and chain==0 must agree with CATEGORY_TO_CHANNEL=FAST."""
    from blender_sync.domain.entities import CATEGORY_TO_CHANNEL
    b = PacketBuilder("me", seq=SeqCounter())
    for cat, channel in CATEGORY_TO_CHANNEL.items():
        if cat is CategoryKind.CONTROL or cat is CategoryKind.SNAPSHOT:
            continue
        # Use a minimal op that includes whatever LWW-key fields the
        # serializer might need; PacketBuilder doesn't care about op
        # contents for chain/seq purposes.
        p = b.build(cat, [{"n": "x", "obj": "y", "mat": "z", "name": "n"}], 1.0)
        if channel is ChannelKind.RELIABLE:
            assert p.chain != 0, f"{cat} should chain, but chain==0"
        else:
            assert p.chain == 0, f"{cat} should not chain, but chain={p.chain}"

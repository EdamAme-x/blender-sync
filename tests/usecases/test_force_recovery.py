"""Force Push / Force Pull recovery regression tests (codex P1-10).

The whole point of a Force packet is to recover when the chain has
drifted too far for NACK/RESEND to repair (e.g. peer joined late, lost
a long burst of packets, the OutboundHistory ring buffer rolled past
the gap, etc.). It is a one-shot full-state realignment.

Codex caught that P1-8 broke this: putting force packets on the
reliable chain made them subject to gap detection, so a peer with a
stale chain would NACK the missing seqs (which the sender will not
resend because it sent a force precisely to skip them) and the force
packet itself would sit in held_back forever.

P1-10 fix: force packets bypass chain verification and instead jump
the receiver's chain state forward to the force packet's reported
chain value (same encoding the sender used: low 16 bits = a, high 16
bits = b). Held-back packets older than the force snapshot are
discarded.
"""
from __future__ import annotations

import json

from blender_sync.domain.entities import (
    CategoryKind, Packet, Peer, Session, SyncConfig,
)
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.domain.policies.packet_builder import PacketBuilder, SeqCounter
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
    cfg = SyncConfig(peer_id="me")
    uc = ApplyRemotePacketUseCase(
        scene, codec, EchoFilter(self_peer_id="me"),
        LWWResolver(), RecordingLogger(), cfg,
    )
    sess = Session(local_peer=Peer(peer_id="me"))
    uc.set_control_handler(sess, lambda s, ops: None)
    return uc, scene, codec


# ----------------------------------------------------------------------
# Force Push apply across a chain gap
# ----------------------------------------------------------------------

def test_force_push_applies_when_receiver_missed_earlier_packets():
    """Sender sends rel1 (lost), rel2 (lost), force3. Receiver only
    sees force3. Pre-fix this would NACK 1..2 forever and never apply.
    Post-fix the force packet realigns the receiver."""
    uc, scene, codec = _make_uc()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    sender = PacketBuilder("alice", SeqCounter())
    rel1 = sender.build(CategoryKind.MATERIAL, [{"mat": "lost1"}], 1.0)
    rel2 = sender.build(CategoryKind.MATERIAL, [{"mat": "lost2"}], 2.0)
    force3 = sender.build(CategoryKind.MATERIAL,
                          [{"mat": "Final", "use_nodes": True}],
                          3.0, force=True)
    # rel1, rel2 never delivered.
    uc.apply_raw(codec.encode(force3))

    # Force packet applies even though chain is fresh on the receiver.
    assert len(scene.applied) == 1
    cat, ops = scene.applied[0]
    assert cat is CategoryKind.MATERIAL
    assert ops[0]["mat"] == "Final"
    # No NACK — force packets bypass gap detection.
    assert nacks == []


def test_force_push_realigns_chain_state_for_subsequent_reliable():
    """After a force packet, the next normal reliable packet must be
    accepted as in-order — i.e., the receiver's chain caught up to
    the force packet's seq + chain values."""
    uc, scene, codec = _make_uc()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    sender = PacketBuilder("alice", SeqCounter())
    # Burn 3 reliable seqs that the receiver never sees.
    sender.build(CategoryKind.MATERIAL, [{"mat": "lost1"}], 1.0)
    sender.build(CategoryKind.MATERIAL, [{"mat": "lost2"}], 2.0)
    sender.build(CategoryKind.MATERIAL, [{"mat": "lost3"}], 3.0)
    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "Snap"}], 4.0, force=True)
    rel_after = sender.build(CategoryKind.MATERIAL,
                             [{"mat": "Next"}], 5.0)

    uc.apply_raw(codec.encode(force))
    assert len(scene.applied) == 1
    assert nacks == []

    uc.apply_raw(codec.encode(rel_after))
    # Both applied, no NACK.
    assert len(scene.applied) == 2
    assert nacks == []


def test_force_push_discards_obsolete_held_back():
    """Receiver had rel3 held back waiting on rel1, rel2 (gap). A
    force packet at seq=10 should drop the obsolete rel3 from the
    held-back queue (it's older than the snapshot)."""
    uc, scene, codec = _make_uc()
    uc.set_nack_emitter(lambda a, f, l: None)

    sender = PacketBuilder("alice", SeqCounter())
    rel1 = sender.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0)
    rel2 = sender.build(CategoryKind.MATERIAL, [{"mat": "B"}], 2.0)
    rel3 = sender.build(CategoryKind.MATERIAL, [{"mat": "C"}], 3.0)

    # Receive only rel3 — it goes into held_back.
    uc.apply_raw(codec.encode(rel3))
    assert 3 in uc._chains["alice"].held_back

    # Sender realizes peer is stuck and emits a force at seq=4.
    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "Snap"}], 4.0, force=True)
    uc.apply_raw(codec.encode(force))

    # Force applied; held_back is purged of obsolete entries.
    assert len(scene.applied) == 1
    assert uc._chains["alice"].held_back == {}


def test_force_push_drains_newer_held_back_after_realign():
    """If a held-back packet has seq > force.seq AND chains correctly
    after the realign, it should drain on the next tick."""
    uc, scene, codec = _make_uc()
    uc.set_nack_emitter(lambda a, f, l: None)

    sender = PacketBuilder("alice", SeqCounter())
    # rel1 dropped, force at seq=2, rel3 arrives early then force.
    sender.build(CategoryKind.MATERIAL, [{"mat": "lost"}], 1.0)
    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "Snap"}], 2.0, force=True)
    rel3 = sender.build(CategoryKind.MATERIAL, [{"mat": "After"}], 3.0)

    # Out-of-order: rel3 first, then force.
    uc.apply_raw(codec.encode(rel3))
    # rel3 sits in held_back at seq=3.
    assert 3 in uc._chains["alice"].held_back

    uc.apply_raw(codec.encode(force))

    # force applied, then rel3 drained because it chains after force.
    cats = [c for c, _ in scene.applied]
    assert cats == [CategoryKind.MATERIAL, CategoryKind.MATERIAL]
    mats = [ops[0]["mat"] for _, ops in scene.applied]
    assert mats == ["Snap", "After"]


def test_force_push_does_not_emit_nack():
    uc, scene, codec = _make_uc()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    sender = PacketBuilder("alice", SeqCounter())
    # Burn 5 seqs, deliver only the force.
    for i in range(5):
        sender.build(CategoryKind.MATERIAL, [{"mat": f"M{i}"}], float(i))
    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "F"}], 5.0, force=True)
    uc.apply_raw(codec.encode(force))

    assert nacks == []


def test_force_push_replaces_state_on_repeat():
    """Force packets are always-authoritative — a repeat realigns the
    chain (idempotent on chain state) and re-applies the snapshot
    payload (force ops bypass LWW gating). This is intentional: force
    is the recovery primitive and must be safe to spam."""
    uc, scene, codec = _make_uc()
    sender = PacketBuilder("alice", SeqCounter())
    f1 = sender.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0, force=True)
    uc.apply_raw(codec.encode(f1))
    assert len(scene.applied) == 1

    # Same packet again — chain state is reset to the same snapshot
    # (no-op realign) and ops re-apply (idempotent at the scene level
    # because the underlying setattr just rewrites the same value).
    uc.apply_raw(codec.encode(f1))
    assert len(scene.applied) == 2  # apply count grows; LWW state stable

    # New force at higher seq+ts applies as well.
    f2 = sender.build(CategoryKind.MATERIAL, [{"mat": "B"}], 2.0, force=True)
    uc.apply_raw(codec.encode(f2))
    assert len(scene.applied) == 3


def test_force_push_after_normal_chain_does_not_break_chain():
    """Force packet in the middle of a normal session must not
    invalidate previously verified history."""
    uc, scene, codec = _make_uc()
    nacks: list = []
    uc.set_nack_emitter(lambda a, f, l: nacks.append((a, f, l)))

    sender = PacketBuilder("alice", SeqCounter())
    rel1 = sender.build(CategoryKind.MATERIAL, [{"mat": "A"}], 1.0)
    rel2 = sender.build(CategoryKind.MATERIAL, [{"mat": "B"}], 2.0)
    force3 = sender.build(CategoryKind.MATERIAL,
                          [{"mat": "C"}], 3.0, force=True)
    rel4 = sender.build(CategoryKind.MATERIAL, [{"mat": "D"}], 4.0)

    for p in (rel1, rel2, force3, rel4):
        uc.apply_raw(codec.encode(p))

    assert len(scene.applied) == 4
    assert nacks == []


def test_force_push_chain_catchup_state():
    """Verify the receiver chain state matches sender after force
    catch-up: expected_seq is force.seq+1, last_verified_seq is
    force.seq, chain a/b are decoded from force.chain."""
    uc, scene, codec = _make_uc()
    sender = PacketBuilder("alice", SeqCounter())

    # Burn 7 seqs the receiver doesn't see.
    for i in range(7):
        sender.build(CategoryKind.MATERIAL, [{"mat": f"M{i}"}], float(i))
    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "F"}], 8.0, force=True)
    uc.apply_raw(codec.encode(force))

    st = uc._chains["alice"]
    assert st.expected_seq == force.seq + 1
    assert st.last_verified_seq == force.seq
    assert st.chain.a == force.chain & 0xFFFF
    assert st.chain.b == (force.chain >> 16) & 0xFFFF


def test_force_push_does_not_touch_lww_for_other_keys():
    """Force apply records LWW for ops in the packet but doesn't
    overwrite unrelated keys."""
    uc, scene, codec = _make_uc()
    sender = PacketBuilder("alice", SeqCounter())

    rel = sender.build(CategoryKind.MATERIAL, [{"mat": "Other"}], 1.0)
    uc.apply_raw(codec.encode(rel))
    # State for Other recorded.
    assert uc._lww.get_state("material:Other") is not None

    force = sender.build(CategoryKind.MATERIAL,
                         [{"mat": "Snap"}], 2.0, force=True)
    uc.apply_raw(codec.encode(force))
    # Other is still there.
    assert uc._lww.get_state("material:Other") is not None
    assert uc._lww.get_state("material:Snap") is not None

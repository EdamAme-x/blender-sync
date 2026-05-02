"""Undo / Redo sync regression tests (UNDO-1 / UNDO-3).

Background: Blender's Ctrl+Z rewinds bpy.data state. Without explicit
support, the local Blender's post-undo state diverges from peers
because:
  - depsgraph_update_post fires for the rewound data, marking
    everything dirty,
  - the next sync_tick sends those changes as normal reliable packets,
  - peers reject them via LWW because their last seen ts is newer
    (the ops they hold are from after the user's edit).

UNDO-1 fix: BpySceneGateway hooks bpy.app.handlers.undo_post and
redo_post. The handler marks every category dirty AND raises a force
flag. SyncTickUseCase reads the flag, builds the next batch with
force=True, and clears the flag. force=True bypasses LWW so peers
authoritatively accept the rewound state.

These tests exercise the dirty-collector contract (no bpy required):
  - SyncTickUseCase respects `consume_undo_pending_force`.
  - The force flag is consumed exactly once per undo (not leaked).
  - Force packets ride the reliable + force seq path on the wire.
"""
from __future__ import annotations

import asyncio
import json

from blender_sync.domain.entities import (
    CategoryKind, Peer, Session, SessionStatus, SyncConfig,
)
from blender_sync.domain.policies.packet_builder import PacketBuilder, SeqCounter
from blender_sync.usecases.sync_tick import SyncTickUseCase
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.clock import FakeClock
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway
from tests.fakes.transport import InMemoryTransport


class _JsonCodec:
    def encode(self, packet):
        return json.dumps(packet.to_wire_dict()).encode("utf-8")

    def decode(self, data):
        from blender_sync.domain.entities import Packet
        return Packet.from_wire_dict(json.loads(data.decode("utf-8")))


def _make_uc():
    asyncio.set_event_loop(asyncio.new_event_loop())
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    builder = PacketBuilder("me", SeqCounter())
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    return uc, scene, transport, session


def test_undo_force_flag_makes_reliable_packets_force_true():
    """User pressed Ctrl+Z. Gateway raised the flag and pre-marked
    dirty. SyncTickUseCase must build force=True packets on RELIABLE
    categories so peers accept the rewound state.

    FAST categories (TRANSFORM/POSE/VIEW3D) are intentionally NOT
    force-flagged — see test_undo_force_strips_force_flag_on_fast_categories.
    """
    uc, scene, transport, session = _make_uc()

    # Simulate the gateway state after undo_post fired.
    scene.undo_pending_force = True
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "Mat", "use_nodes": True}]
    scene.dirty[CategoryKind.MESH] = [{"obj": "Cube"}]

    uc.tick(session)

    assert len(transport.sent) == 2
    decoded = [_JsonCodec().decode(d) for _, d in transport.sent]
    assert all(p.force for p in decoded)


def test_undo_flag_consumed_once_per_undo():
    """Repeated ticks after a single undo must NOT keep emitting force
    packets. Only the first post-undo tick should be force=True (on
    RELIABLE categories — FAST categories never force).
    """
    uc, scene, transport, session = _make_uc()

    scene.undo_pending_force = True
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "Mat", "use_nodes": True}]
    uc.tick(session)
    assert scene.undo_force_consumed == 1

    # Next tick — gateway didn't raise the flag again, so this must
    # be a normal (non-force) packet.
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "Mat", "use_nodes": False}]
    uc.tick(session)
    assert scene.undo_force_consumed == 1   # not bumped
    decoded = [_JsonCodec().decode(d) for _, d in transport.sent]
    assert decoded[0].force is True
    assert decoded[1].force is False


def test_undo_with_no_dirty_does_nothing():
    """If undo somehow fires but nothing is dirty (impossible in real
    Blender, but defensive), the tick should be a no-op."""
    uc, scene, transport, session = _make_uc()
    scene.undo_pending_force = True
    uc.tick(session)
    assert transport.sent == []
    # Flag stayed up because consume happens AFTER we know there are
    # ops to send. Actually the code reads it before iterating ops, so
    # it gets consumed. Either contract is OK; the practical
    # invariant is "no force packets emitted" which we just asserted.


def test_undo_force_does_not_leak_to_other_session_state():
    """If session is not LIVE, the force flag must NOT be drained
    yet (otherwise the user could press Ctrl+Z while disconnected and
    silently lose the rebroadcast on reconnect)."""
    uc, scene, transport, session = _make_uc()
    session.status = SessionStatus.IDLE

    scene.undo_pending_force = True
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube"}]
    uc.tick(session)

    # Tick is a no-op due to session status, so the flag is NOT
    # consumed.
    assert transport.sent == []
    assert scene.undo_pending_force is True
    assert scene.undo_force_consumed == 0


def test_undo_force_skipped_when_applying_remote():
    """Echo guard takes precedence — even with the undo flag, if we're
    in the middle of applying a remote packet, don't broadcast."""
    uc, scene, transport, session = _make_uc()
    scene.applying_remote = True
    scene.undo_pending_force = True
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube"}]
    uc.tick(session)
    assert transport.sent == []
    assert scene.undo_pending_force is True   # not consumed


def test_undo_flag_consumed_even_when_grouped_is_empty():
    """P2-19: if undo fires but the dirty batch is empty (e.g. all
    categories filtered off, or hash-deduped), the flag must still be
    consumed. Otherwise a later unrelated reliable edit would
    silently go out as force=True and overwrite newer peer state."""
    uc, scene, transport, session = _make_uc()

    # Empty filter = no enabled categories → grouped will be empty.
    scene.undo_pending_force = True
    # No dirty added — collect returns []
    uc.tick(session)

    # The flag must have been read despite the empty batch.
    assert scene.undo_force_consumed == 1
    assert scene.undo_pending_force is False
    assert transport.sent == []   # nothing to send

    # Now a normal reliable edit arrives. It must NOT be force=True.
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "M"}]
    uc.tick(session)
    decoded = [_JsonCodec().decode(d) for _, d in transport.sent]
    assert len(decoded) == 1
    assert decoded[0].force is False


def test_undo_force_keeps_flag_on_all_categories_post_p2_28():
    """After P2-28, force=True promotes any category — including
    FAST ones — to the reliable chain. The earlier P1-14 strip is
    no longer needed (and is actively harmful: it would drop undo
    transforms entirely if their FAST packet were lost in flight).

    Contract: undo tick produces force=True on every category, and
    every packet rides the reliable counter + chain.
    """
    asyncio.set_event_loop(asyncio.new_event_loop())
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    rel_seq = SeqCounter()
    fast_seq = SeqCounter()
    builder = PacketBuilder("me", rel_seq, unreliable_seq=fast_seq)
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)

    scene.undo_pending_force = True
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube", "loc": [0, 0, 0]}]
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "M", "use_nodes": True}]
    scene.dirty[CategoryKind.POSE] = [{"obj": "Arm"}]
    scene.dirty[CategoryKind.VIEW3D] = [{}]

    uc.tick(session)

    assert len(transport.sent) == 4
    decoded = [_JsonCodec().decode(d) for _, d in transport.sent]
    # Every category force=True — the strip from P1-14 is reverted.
    assert all(p.force for p in decoded)
    # Every packet rides the reliable counter (P2-28 promotion).
    assert rel_seq.current == 4
    assert fast_seq.current == 0


def test_undo_force_uses_reliable_counter_for_all_categories():
    """All force packets — including TRANSFORM — must consume the
    reliable seq counter so NACK/RESEND covers them. This is the
    P2-28 promotion exercised end-to-end via SyncTick."""
    asyncio.set_event_loop(asyncio.new_event_loop())
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    rel_seq = SeqCounter()
    fast_seq = SeqCounter()
    builder = PacketBuilder("me", rel_seq, unreliable_seq=fast_seq)
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)

    scene.undo_pending_force = True
    scene.dirty[CategoryKind.MATERIAL] = [{"mat": "M", "use_nodes": True}]
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube"}]
    uc.tick(session)

    decoded = [_JsonCodec().decode(d) for _, d in transport.sent]
    # Both packets are force=True per the new policy.
    assert all(p.force for p in decoded)
    # Both ride the reliable counter (P2-28 promotion).
    assert rel_seq.current == 2
    assert fast_seq.current == 0


# ----------------------------------------------------------------------
# Direct gateway tests (no bpy)
# ----------------------------------------------------------------------

def test_consume_undo_pending_force_resets_flag():
    """Contract on the FakeSceneGateway: returns True once after the
    flag is set, then False until set again."""
    scene = FakeSceneGateway()
    assert scene.consume_undo_pending_force() is False
    scene.undo_pending_force = True
    assert scene.consume_undo_pending_force() is True
    assert scene.consume_undo_pending_force() is False


def test_real_gateway_undo_handler_marks_dirty_and_sets_flag():
    """Even without bpy, BpySceneGateway exposes a `_make_undo_handler`
    that returns a callable. We can verify the contract by stubbing
    bpy with a minimal duck-typed module and invoking the handler."""
    import types
    import sys

    # Build a minimal fake bpy module.
    fake_bpy = types.ModuleType("bpy")
    fake_data = types.SimpleNamespace(
        objects=[],
        materials=[],
        meshes=[],
        cameras=[],
        lights=[],
        collections=[],
        images=[],
        armatures=[],
        node_groups=[],
        textures=[],
        curves=[],
        lattices=[],
        metaballs=[],
        sounds=[],
        volumes=None,
        pointclouds=None,
        grease_pencils=None,
        grease_pencils_v3=None,
    )
    fake_bpy.data = fake_data
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False,
        handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()

    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        assert gw._undo_pending_force is False

        handler = gw._undo_handler
        # Invoke as Blender would: scene + depsgraph args.
        handler(scene=None, depsgraph=None)

        # Singleton flags marked.
        assert gw._tracker.render is True
        assert gw._tracker.compositor is True
        assert gw._tracker.scene_world is True
        assert gw._tracker.view3d is True
        # Force broadcast flag raised.
        assert gw._undo_pending_force is True

        # Consume drains the flag.
        assert gw.consume_undo_pending_force() is True
        assert gw._undo_pending_force is False
        # And subsequent calls return False.
        assert gw.consume_undo_pending_force() is False
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_mesh_objects_not_datablocks():
    """P2-15: MeshCategoryHandler resolves via bpy.data.objects.get,
    so the undo walk must mark *object* names of type MESH, not the
    underlying mesh datablock names. After Undo of an object whose
    name differs from its mesh datablock name, the rebroadcast must
    contain the object's geometry."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    class FakeMeshObj:
        name = "Cube_renamed"
        type = "MESH"
        modifiers = ()
        particle_systems = ()
        data = None

    class FakeOtherObj:
        name = "Light"
        type = "LIGHT"
        modifiers = ()
        particle_systems = ()
        data = None

    fake_bpy.data = types.SimpleNamespace(
        objects=[FakeMeshObj(), FakeOtherObj()],
        materials=[], meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw._undo_handler(scene=None, depsgraph=None)

        # Mesh dirty set must contain the OBJECT name, not the
        # bpy.data.meshes name.
        assert "Cube_renamed" in gw._tracker.meshes_committed
        # Light shouldn't be in meshes.
        assert "Light" not in gw._tracker.meshes_committed
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_objects_with_empty_modifier_stack():
    """P2-16: an object whose modifier stack was just emptied by an
    Undo must still be marked dirty so the modifier handler emits an
    empty list to peers, clearing their stale stack."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    class EmptyModObj:
        name = "JustCleared"
        type = "MESH"
        modifiers = ()  # falsy — empty modifiers list
        particle_systems = ()
        data = None

    fake_bpy.data = types.SimpleNamespace(
        objects=[EmptyModObj()],
        materials=[], meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw._undo_handler(scene=None, depsgraph=None)

        # Modifier set must contain the object even with an empty
        # modifier stack — without this, peers retain the old stack.
        objs_with_modifier_dirty = {obj for obj, _ in gw._tracker.modifiers}
        assert "JustCleared" in objs_with_modifier_dirty
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_objects_with_empty_particle_systems():
    """P2-18: an object whose particle systems were ALL removed by
    Undo must still be in the particle dirty set so peers can clear
    their stale particle stack."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    class EmptyPSObj:
        name = "JustClearedParticles"
        type = "MESH"
        modifiers = ()
        particle_systems = ()  # falsy — empty list
        data = None

    fake_bpy.data = types.SimpleNamespace(
        objects=[EmptyPSObj()],
        materials=[], meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw._undo_handler(scene=None, depsgraph=None)

        assert "JustClearedParticles" in gw._tracker.particles
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_objects_with_empty_shape_keys():
    """P2-18: an object whose shape keys were all removed by Undo
    must still be in the shape_keys dirty set."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    class FakeMesh:
        # Mesh data with NO shape keys (data.shape_keys is None).
        shape_keys = None

    class EmptySKObj:
        name = "JustClearedSK"
        type = "MESH"
        modifiers = ()
        particle_systems = ()
        data = FakeMesh()

    fake_bpy.data = types.SimpleNamespace(
        objects=[EmptySKObj()],
        materials=[], meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw._undo_handler(scene=None, depsgraph=None)

        assert "JustClearedSK" in gw._tracker.shape_keys
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_driver_only_animation_owners():
    """P2-20: an owner with animation_data but no active Action (e.g.
    drivers-only or NLA-only) must still appear in the animation
    dirty set after Undo. The cached _action_to_users reverse lookup
    only sees Action-bearing owners, so we walk live datablocks
    directly for the undo path."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    # Object with animation_data but ad.action is None — pure driver
    # / NLA case.
    class FakeAnimData:
        action = None
        drivers = ()
        nla_tracks = ()

    class DriverObj:
        name = "DriverDriven"
        type = "MESH"
        modifiers = ()
        particle_systems = ()
        data = None
        animation_data = FakeAnimData()

    # Material with the same shape.
    class DriverMat:
        name = "DriverMat"
        animation_data = FakeAnimData()

    fake_bpy.data = types.SimpleNamespace(
        objects=[DriverObj()],
        materials=[DriverMat()],
        meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        worlds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw._undo_handler(scene=None, depsgraph=None)

        # Both driver-only owners must be in the animation dirty set.
        assert "object:DriverDriven" in gw._tracker.animations
        assert "material:DriverMat" in gw._tracker.animations
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_marks_previously_animated_owners_after_clear():
    """P2-24: an owner that *had* animation_data on a previous undo
    walk but whose animation_data was cleared by Ctrl+Z must still
    be marked dirty, so the serializer's clear-op reaches peers and
    they drop their stale Action / drivers / NLA."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")

    # First walk: object has animation_data. Second walk: it's None.
    class FakeAD:
        action = None
        drivers = ()
        nla_tracks = ()

    class TogglingObj:
        def __init__(self, *, animated: bool):
            self.name = "Cube"
            self.type = "MESH"
            self.modifiers = ()
            self.particle_systems = ()
            self.data = None
            self.animation_data = FakeAD() if animated else None

    state = {"obj": TogglingObj(animated=True)}

    fake_bpy.data = types.SimpleNamespace(
        objects=[state["obj"]],
        materials=[], meshes=[], cameras=[], lights=[], collections=[],
        images=[], armatures=[], node_groups=[], textures=[],
        curves=[], lattices=[], metaballs=[], sounds=[],
        worlds=[],
        volumes=None, pointclouds=None,
        grease_pencils=None, grease_pencils_v3=None,
    )
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())

        # First undo walk: animation_data is present.
        gw._undo_handler(scene=None, depsgraph=None)
        assert "object:Cube" in gw._tracker.animations
        assert ("object", "Cube") in gw._previously_animated

        # Reset tracker. User performs a Ctrl+Z that clears
        # animation_data on the object.
        gw._tracker.animations.clear()
        state["obj"] = TogglingObj(animated=False)
        fake_bpy.data.objects[:] = [state["obj"]]

        # Second undo walk: animation_data is None now. The owner
        # must still be marked because we remembered it from before.
        gw._undo_handler(scene=None, depsgraph=None)
        assert "object:Cube" in gw._tracker.animations
        # And the previously-animated set drops it now (live walk
        # didn't see it). Next undo cycle won't redundantly mark it.
        assert ("object", "Cube") not in gw._previously_animated
    finally:
        sys.modules.pop("bpy", None)


def test_real_gateway_undo_handler_skips_when_applying_remote():
    """Echo guard: undo_post must no-op if we're currently applying a
    remote packet (the rewind we'd see is the legitimate result of
    the remote's authoritative state, not a local user undo)."""
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")
    fake_bpy.data = types.SimpleNamespace(objects=[])
    fake_bpy.types = types.SimpleNamespace()
    fake_bpy.app = types.SimpleNamespace(
        background=False, handlers=types.SimpleNamespace(),
    )
    fake_bpy.context = types.SimpleNamespace(scene=None, screen=None)
    fake_bpy.msgbus = types.SimpleNamespace()
    sys.modules["bpy"] = fake_bpy
    try:
        from blender_sync.adapters.scene.bpy_scene_gateway import (
            BpySceneGateway,
        )
        from blender_sync.domain.policies.dirty_tracker import DirtyTracker

        gw = BpySceneGateway(logger=RecordingLogger(), tracker=DirtyTracker())
        gw.set_applying_remote(True)
        gw._undo_handler(scene=None, depsgraph=None)
        assert gw._undo_pending_force is False
        assert gw._tracker.render is False
    finally:
        sys.modules.pop("bpy", None)

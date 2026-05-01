"""Per-op LWW key regression tests (codex P1-2).

The bug: `lww_key` returned `<category>:misc` for every category not
explicitly handled. When a single packet carried multiple ops for one
of those categories (Sound, Volume, PointCloud, Image, Camera, ...,
plus Deletion / Rename which always carry batched ops), the LWW
resolver saw all ops mapping to the same key + same (seq, ts, author)
tuple. The first op recorded the slot; the rest were rejected as
"duplicates" of the first.

Result: packet "delete A, B, C" would only delete A; packet "rename
A, B" would only rename A; force-sync of 5 cameras would only update
the first one. Catastrophic for production fan-out.

Fix: every category extracts its op-level identifier into the key.
"""
from __future__ import annotations

from blender_sync.domain.entities import CategoryKind, Packet, SyncConfig
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.domain.policies.packet_builder import lww_key
from blender_sync.usecases.apply_remote import ApplyRemotePacketUseCase
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway


# ----------------------------------------------------------------------
# Pure key-generation contract
# ----------------------------------------------------------------------

def test_deletion_key_distinguishes_kind_and_name():
    a = lww_key(CategoryKind.DELETION, {"kind": "object", "name": "Cube"})
    b = lww_key(CategoryKind.DELETION, {"kind": "object", "name": "Sphere"})
    c = lww_key(CategoryKind.DELETION, {"kind": "material", "name": "Cube"})
    assert a != b
    assert a != c
    assert "Cube" in a and "Sphere" in b


def test_rename_key_distinguishes_uid():
    a = lww_key(CategoryKind.RENAME,
                {"kind": "object", "uid": "abc123", "old": "A", "new": "B"})
    b = lww_key(CategoryKind.RENAME,
                {"kind": "object", "uid": "def456", "old": "X", "new": "Y"})
    assert a != b


def test_datablock_categories_key_by_name():
    cases = [
        (CategoryKind.IMAGE,        {"name": "BGM"},     "image"),
        (CategoryKind.TEXTURE,      {"name": "T1"},      "texture"),
        (CategoryKind.NODE_GROUP,   {"name": "GN"},      "node_group"),
        (CategoryKind.ARMATURE,     {"name": "Arm"},     "armature"),
        (CategoryKind.CAMERA,       {"name": "Cam"},     "camera"),
        (CategoryKind.LIGHT,        {"name": "Sun"},     "light"),
        (CategoryKind.COLLECTION,   {"name": "Col"},     "collection"),
        (CategoryKind.GREASE_PENCIL,{"name": "GP"},      "grease_pencil"),
        (CategoryKind.CURVE,        {"name": "Cu"},      "curve"),
        (CategoryKind.LATTICE,      {"name": "L"},       "lattice"),
        (CategoryKind.METABALL,     {"name": "Mb"},      "metaball"),
        (CategoryKind.VOLUME,       {"name": "V"},       "volume"),
        (CategoryKind.POINT_CLOUD,  {"name": "PC"},      "point_cloud"),
        (CategoryKind.SOUND,        {"name": "S"},       "sound"),
    ]
    for cat, op, prefix in cases:
        k1 = lww_key(cat, op)
        k2 = lww_key(cat, {"name": op["name"] + "_X"})
        assert k1.startswith(f"{prefix}:")
        assert k1 != k2, f"{cat}: same key for distinct names"
        # No more `:misc` fallback for these.
        assert not k1.endswith(":misc")


def test_object_side_categories_key_by_obj():
    cases = [
        (CategoryKind.MODIFIER,        {"obj": "Cube"}),
        (CategoryKind.MATERIAL_SLOTS,  {"obj": "Cube"}),
        (CategoryKind.MESH,            {"obj": "Cube"}),
        (CategoryKind.POSE,            {"obj": "Armature"}),
        (CategoryKind.SHAPE_KEYS,      {"obj": "Cube"}),
        (CategoryKind.CONSTRAINTS,     {"obj": "Cube"}),
        (CategoryKind.PARTICLE,        {"obj": "Hairy"}),
    ]
    for cat, op in cases:
        k1 = lww_key(cat, op)
        k2 = lww_key(cat, {"obj": op["obj"] + "_2"})
        assert k1 != k2
        assert not k1.endswith(":misc")


def test_animation_key_distinguishes_owner_type():
    """`object:Cube` and `material:Cube` legitimately collide if we
    only key by owner name. owner_type must be in the key."""
    a = lww_key(CategoryKind.ANIMATION,
                {"owner": "Cube", "owner_type": "object"})
    b = lww_key(CategoryKind.ANIMATION,
                {"owner": "Cube", "owner_type": "material"})
    assert a != b


def test_singletons_share_key():
    """Render / Compositor / Scene / View3D are scene-level — one op
    per packet — so sharing a key across the category is correct."""
    a = lww_key(CategoryKind.RENDER, {"scene": "Scene"})
    b = lww_key(CategoryKind.RENDER, {"scene": "Other"})
    assert a == b
    a = lww_key(CategoryKind.COMPOSITOR, {})
    b = lww_key(CategoryKind.COMPOSITOR, {"any": "thing"})
    assert a == b
    a = lww_key(CategoryKind.VIEW3D, {})
    b = lww_key(CategoryKind.VIEW3D, {})
    assert a == b


def test_vse_strip_keyed_by_scene():
    """VSE ops always carry one entry per Scene; key by scene name so
    cross-scene VSE ops in the same packet (rare) don't collide."""
    a = lww_key(CategoryKind.VSE_STRIP, {"scene": "Main"})
    b = lww_key(CategoryKind.VSE_STRIP, {"scene": "Side"})
    assert a != b


# ----------------------------------------------------------------------
# End-to-end: ApplyRemotePacketUseCase must apply ALL ops in a multi-op
# packet, not just the first.
# ----------------------------------------------------------------------

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
    return uc, scene, codec


def test_deletion_packet_with_multiple_ops_applies_all():
    """Pre-fix: only the first deletion went through. With a per-op key,
    all 5 must be passed to apply_ops."""
    uc, scene, codec = _make_uc()
    ops = [
        {"kind": "object", "name": "A"},
        {"kind": "object", "name": "B"},
        {"kind": "material", "name": "M1"},
        {"kind": "image", "name": "Img"},
        {"kind": "object", "name": "C"},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.DELETION, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    cat, applied_ops = scene.applied[0]
    assert cat is CategoryKind.DELETION
    assert len(applied_ops) == 5
    names = [(o["kind"], o["name"]) for o in applied_ops]
    assert ("object", "A") in names
    assert ("object", "C") in names


def test_rename_packet_with_multiple_ops_applies_all():
    uc, scene, codec = _make_uc()
    ops = [
        {"kind": "object",  "uid": "u1", "old": "A", "new": "A2"},
        {"kind": "object",  "uid": "u2", "old": "B", "new": "B2"},
        {"kind": "material","uid": "u3", "old": "M", "new": "M2"},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.RENAME, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    cat, applied_ops = scene.applied[0]
    assert cat is CategoryKind.RENAME
    assert len(applied_ops) == 3


def test_camera_force_sync_with_multiple_cameras_applies_all():
    """Force-sync packet for 3 cameras. Pre-fix this fell through to
    the misc bucket and only Cam1 made it."""
    uc, scene, codec = _make_uc()
    ops = [
        {"name": "Cam1", "props": {"lens": 35.0}},
        {"name": "Cam2", "props": {"lens": 50.0}},
        {"name": "Cam3", "props": {"lens": 85.0}},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.CAMERA, ops=tuple(ops),
        force=True,
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    cat, applied_ops = scene.applied[0]
    assert cat is CategoryKind.CAMERA
    assert len(applied_ops) == 3
    names = [o["name"] for o in applied_ops]
    assert names == ["Cam1", "Cam2", "Cam3"]


def test_sound_packet_with_multiple_ops_applies_all():
    uc, scene, codec = _make_uc()
    ops = [
        {"name": "BGM", "props": {"filepath": "//a.wav"}},
        {"name": "SFX", "props": {"filepath": "//b.wav"}},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.SOUND, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    _, applied_ops = scene.applied[0]
    assert len(applied_ops) == 2


def test_volume_packet_with_multiple_ops_applies_all():
    uc, scene, codec = _make_uc()
    ops = [
        {"name": "Vol1", "filepath": "//a.vdb"},
        {"name": "Vol2", "filepath": "//b.vdb"},
        {"name": "Vol3", "filepath": "//c.vdb"},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.VOLUME, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    _, applied_ops = scene.applied[0]
    assert len(applied_ops) == 3


def test_object_side_packet_with_multiple_objects_applies_all():
    """Modifier op for 4 distinct objects — must all apply."""
    uc, scene, codec = _make_uc()
    ops = [
        {"obj": "Cube",    "modifiers": []},
        {"obj": "Sphere",  "modifiers": []},
        {"obj": "Cone",    "modifiers": []},
        {"obj": "Cyl",     "modifiers": []},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.MODIFIER, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    _, applied_ops = scene.applied[0]
    assert len(applied_ops) == 4


def test_animation_owner_type_collisions_resolve_separately():
    """Object 'X' animation and Material 'X' animation in same packet
    must not collide via owner-name-only keys."""
    uc, scene, codec = _make_uc()
    ops = [
        {"owner": "X", "owner_type": "object",   "action": {"name": "ObjAct"}},
        {"owner": "X", "owner_type": "material", "action": {"name": "MatAct"}},
    ]
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="alice",
        category=CategoryKind.ANIMATION, ops=tuple(ops),
    )
    uc.apply_raw(codec.encode(pkt))
    assert len(scene.applied) == 1
    _, applied = scene.applied[0]
    assert len(applied) == 2


def test_singletons_still_apply_one_op_normally():
    """Render is a singleton — single op per packet — and the LWW
    behavior must continue to gate older ops correctly."""
    uc, scene, codec = _make_uc()
    p1 = Packet(version=1, seq=1, ts=10.0, author="alice",
                category=CategoryKind.RENDER,
                ops=({"render": {"resolution_x": 1920}},))
    p2 = Packet(version=1, seq=2, ts=20.0, author="alice",
                category=CategoryKind.RENDER,
                ops=({"render": {"resolution_x": 3840}},),
                force=True)
    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p2))
    # Both should pass — sequential, increasing ts.
    assert len(scene.applied) == 2

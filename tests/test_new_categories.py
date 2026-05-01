"""Tests for newly added sync categories: Camera, Light, MaterialSlots,
plus the SyncFilters.enabled_categories() central source-of-truth.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from blender_sync.domain.entities import (
    CATEGORY_TO_CHANNEL,
    CategoryKind,
    ChannelKind,
    MeshSyncMode,
    SyncFilters,
)
from blender_sync.domain.policies.dirty_tracker import DirtyTracker


_OFF_KW = dict(
    transform=False, material=False, modifier=False,
    mesh=MeshSyncMode(on_edit_exit=False, during_edit=False),
    compositor=False, render=False, scene_world=False,
    visibility=False, camera=False, light=False,
    collection=False, animation=False, image=False,
    armature=False, pose=False, shape_keys=False,
    constraints=False, grease_pencil=False, curve=False, particle=False,
    node_group=False, texture=False, lattice=False, metaball=False,
    volume=False, point_cloud=False, vse_strip=False,
    sound=False, view3d=False,
)


def test_enabled_categories_default_includes_all():
    cats = SyncFilters().enabled_categories()
    for needed in (
        CategoryKind.TRANSFORM,
        CategoryKind.MATERIAL,
        CategoryKind.MATERIAL_SLOTS,
        CategoryKind.MODIFIER,
        CategoryKind.MESH,
        CategoryKind.COMPOSITOR,
        CategoryKind.RENDER,
        CategoryKind.SCENE,
        CategoryKind.VISIBILITY,
        CategoryKind.CAMERA,
        CategoryKind.LIGHT,
        CategoryKind.COLLECTION,
        CategoryKind.ANIMATION,
        CategoryKind.IMAGE,
        CategoryKind.DELETION,
        CategoryKind.RENAME,
        CategoryKind.ARMATURE,
        CategoryKind.POSE,
        CategoryKind.SHAPE_KEYS,
        CategoryKind.CONSTRAINTS,
        CategoryKind.GREASE_PENCIL,
        CategoryKind.CURVE,
        CategoryKind.PARTICLE,
        CategoryKind.NODE_GROUP,
        CategoryKind.TEXTURE,
        CategoryKind.LATTICE,
        CategoryKind.METABALL,
        CategoryKind.VOLUME,
        CategoryKind.POINT_CLOUD,
        CategoryKind.VSE_STRIP,
        CategoryKind.SOUND,
        CategoryKind.VIEW3D,
    ):
        assert needed in cats, f"missing {needed}"


def test_enabled_categories_respects_individual_flags():
    f = SyncFilters(**{**_OFF_KW, "transform": True})
    # DELETION + RENAME are forced on regardless of filters to prevent
    # state drift on peers.
    assert f.enabled_categories() == frozenset({
        CategoryKind.TRANSFORM, CategoryKind.DELETION, CategoryKind.RENAME,
    })


def test_material_flag_implies_material_slots():
    f = SyncFilters(**{**_OFF_KW, "material": True})
    cats = f.enabled_categories()
    assert CategoryKind.MATERIAL in cats
    assert CategoryKind.MATERIAL_SLOTS in cats


def test_mesh_flag_combines_two_subflags():
    f = SyncFilters(**{
        **_OFF_KW,
        "mesh": MeshSyncMode(on_edit_exit=False, during_edit=True),
    })
    assert CategoryKind.MESH in f.enabled_categories()


def test_dirty_tracker_carries_camera_light():
    t = DirtyTracker()
    t.mark_camera("Camera")
    t.mark_light("Sun")
    snap = t.flush()
    assert "Camera" in snap.cameras
    assert "Sun" in snap.lights
    assert t.flush().is_empty()


def test_new_categories_use_reliable_channel():
    assert CATEGORY_TO_CHANNEL[CategoryKind.CAMERA] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.LIGHT] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.MATERIAL_SLOTS] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.ARMATURE] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.SHAPE_KEYS] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.NODE_GROUP] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.TEXTURE] is ChannelKind.RELIABLE
    # POSE rides the FAST lane like transforms (high-frequency animation).
    assert CATEGORY_TO_CHANNEL[CategoryKind.POSE] is ChannelKind.FAST


class _FakeSnap:
    objects_transform = frozenset()
    objects_visibility = frozenset()
    materials = frozenset()
    modifiers = frozenset()
    meshes_committed = frozenset()
    meshes_editing = frozenset()
    cameras = frozenset()
    lights = frozenset()
    collections = frozenset()
    animations = frozenset()
    images = frozenset()
    armatures = frozenset()
    poses = frozenset()
    shape_keys = frozenset()
    grease_pencils = frozenset()
    curves = frozenset()
    particles = frozenset()
    node_groups = frozenset()
    textures = frozenset()
    lattices = frozenset()
    metaballs = frozenset()
    volumes = frozenset()
    point_clouds = frozenset()
    sounds = frozenset()
    vse_strip = False
    view3d = False
    render = False
    compositor = False
    scene_world = False


class _FakePointAttrData:
    def __init__(self, n: int, prop: str):
        self.n = n
        self.prop = prop

    def __len__(self):
        return self.n

    def __iter__(self):
        if self.prop == "vector":
            for _ in range(self.n):
                yield SimpleNamespace(vector=(1.0, 2.0, 3.0))
        else:
            for _ in range(self.n):
                yield SimpleNamespace(value=0.5)

    def foreach_get(self, key, buf):
        assert key == self.prop
        try:
            if self.prop == "vector":
                buf[:] = 1.0
            else:
                buf[:] = 0.5
            return
        except Exception:
            pass
        value = 1.0 if self.prop == "vector" else 0.5
        for i in range(len(buf)):
            buf[i] = value


class _FakePointAttr:
    def __init__(self, n: int, prop: str):
        self.data = _FakePointAttrData(n, prop)


class _FakePointAttrs:
    def __init__(self, n: int):
        self._d = {
            "position": _FakePointAttr(n, "vector"),
            "radius": _FakePointAttr(n, "value"),
        }

    def get(self, k):
        return self._d.get(k)


class _FakePoints:
    def __init__(self, n: int):
        self.n = n

    def __len__(self):
        return self.n


class _FakePointCloud:
    def __init__(self, name: str, n: int):
        self.name = name
        self.points = _FakePoints(n)
        self.attributes = _FakePointAttrs(n)


class _FakeSceneMap:
    def __init__(self, scenes):
        self._scenes = list(scenes)
        self._by_name = {s.name: s for s in self._scenes}

    def __iter__(self):
        return iter(self._scenes)

    def get(self, name):
        return self._by_name.get(name)


class _FakeVSEScene:
    def __init__(self, name: str, collection=None, strips_all=None):
        self.name = name
        self._collection = collection
        self._strips_all = list(strips_all or [])
        self.sequence_editor = None
        self.clear_count = 0
        self.create_count = 0

    def sequence_editor_clear(self):
        self.clear_count += 1
        self.sequence_editor = None

    def sequence_editor_create(self):
        self.create_count += 1
        collection = self._collection if self._collection is not None else []
        self.sequence_editor = SimpleNamespace(
            show_overlay_frame=False,
            strips=collection,
            sequences=[],
            strips_all=self._strips_all,
            sequences_all=self._strips_all,
        )


class _FakeVSECreatedStrip:
    def __init__(self, name: str, stype: str):
        self.name = name
        self.type = stype
        self.channel = 0
        self.frame_start = 0
        self.transform = None


class _FakeVSECollection:
    def __init__(self):
        self.calls = []
        self.created = []

    def _make(self, method: str, name: str, stype: str, *args):
        strip = _FakeVSECreatedStrip(name, stype)
        self.calls.append((method, name, *args))
        self.created.append(strip)
        return strip

    def new_meta(self, name, channel, frame_start):
        return self._make("new_meta", name, "META", channel, frame_start)

    def new_clip(self, name, clip, channel, frame_start):
        return self._make("new_clip", name, "MOVIECLIP", clip, channel, frame_start)

    def new_mask(self, name, mask, channel, frame_start):
        return self._make("new_mask", name, "MASK", mask, channel, frame_start)


def _install_fake_vse_bpy(monkeypatch, scenes, active_scene):
    fake_bpy = SimpleNamespace(
        data=SimpleNamespace(scenes=_FakeSceneMap(scenes)),
        context=SimpleNamespace(scene=active_scene),
    )
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    return fake_bpy


def test_camera_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.camera import CameraCategoryHandler
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        cameras = frozenset({"Camera"})

    h = CameraCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_light_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.light import LightCategoryHandler
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        lights = frozenset({"Sun"})

    h = LightCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_material_slots_uses_transform_dirty():
    from blender_sync.adapters.scene.categories.base import DirtyContext
    from blender_sync.adapters.scene.categories.material_slots import (
        MaterialSlotsCategoryHandler,
    )

    class S(_FakeSnap):
        objects_transform = frozenset({"Cube"})

    h = MaterialSlotsCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_armature_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.armature import ArmatureCategoryHandler
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        armatures = frozenset({"Armature"})

    h = ArmatureCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_pose_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.pose import PoseCategoryHandler
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        poses = frozenset({"Armature"})

    h = PoseCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_shape_keys_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.shape_keys import (
        ShapeKeysCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        shape_keys = frozenset({"Cube"})

    h = ShapeKeysCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_node_group_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.node_group import (
        NodeGroupCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        node_groups = frozenset({"GroupA"})

    h = NodeGroupCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_texture_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.texture import (
        TextureCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        textures = frozenset({"Tex"})

    h = TextureCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_lattice_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.lattice import (
        LatticeCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        lattices = frozenset({"Lattice"})

    h = LatticeCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_metaball_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.metaball import (
        MetaballCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        metaballs = frozenset({"Mball"})

    h = MetaballCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_volume_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.volume import (
        VolumeCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        volumes = frozenset({"Volume"})

    h = VolumeCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_point_cloud_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        point_clouds = frozenset({"PointCloud"})

    h = PointCloudCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_point_cloud_serialize_uses_attribute_api():
    """Locks in the Blender 5 attribute API: position via 'vector',
    radius via 'value'. Caught a real bug pre-merge where the handler
    used the legacy `pc.points.foreach_get('position', ...)` path that
    silently failed."""
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
    )

    calls: list[tuple[str, str]] = []

    class FakeAttrData:
        def __init__(self, prop, n):
            self.prop, self.n = prop, n
        def foreach_get(self, key, buf):
            calls.append((self.prop, key))
            for i in range(min(len(buf), self.n)):
                buf[i] = 0.0

    class FakeAttr:
        def __init__(self, prop, n):
            self.data = FakeAttrData(prop, n)

    class FakeAttrs:
        def __init__(self, n):
            self._d = {
                "position": FakeAttr("position", n * 3),
                "radius": FakeAttr("radius", n),
            }
        def get(self, k):
            return self._d.get(k)

    class FakePoints:
        def __init__(self, n): self.n = n
        def __len__(self): return self.n

    class FakePC:
        def __init__(self, name, n):
            self.name = name
            self.points = FakePoints(n)
            self.attributes = FakeAttrs(n)

    h = PointCloudCategoryHandler()
    out = h._serialize(FakePC("Cloud", 4))
    assert out["name"] == "Cloud"
    assert out["count"] == 4
    # The handler must read attribute 'position' with key 'vector' and
    # attribute 'radius' with key 'value' — not 'position' on points.
    assert ("position", "vector") in calls
    assert ("radius", "value") in calls
    assert len(out["positions"]) == 12
    assert len(out["radii"]) == 4


def test_point_cloud_serialize_truncates_oversize_when_limit_passed():
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
        _BUILD_FULL_MAX_POINTS,
    )

    h = PointCloudCategoryHandler()
    out = h._serialize(_FakePointCloud("Big", _BUILD_FULL_MAX_POINTS + 1),
                       max_points=_BUILD_FULL_MAX_POINTS)
    assert out["truncated"] is True
    assert "positions" not in out
    assert "radii" not in out


def test_point_cloud_serialize_limit_is_inclusive_not_truncated():
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
        _BUILD_FULL_MAX_POINTS,
    )

    h = PointCloudCategoryHandler()
    out = h._serialize(
        _FakePointCloud("Limit", _BUILD_FULL_MAX_POINTS),
        max_points=_BUILD_FULL_MAX_POINTS,
    )
    assert out["count"] == _BUILD_FULL_MAX_POINTS
    assert "truncated" not in out
    assert len(out["positions"]) == _BUILD_FULL_MAX_POINTS * 3
    assert len(out["radii"]) == _BUILD_FULL_MAX_POINTS


def test_point_cloud_serialize_none_limit_sends_100k_points():
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
        _BUILD_FULL_MAX_POINTS,
    )

    h = PointCloudCategoryHandler()
    pc = _FakePointCloud("Big", 100_000)
    full = h._serialize(pc, max_points=None)
    truncated = h._serialize(pc, max_points=_BUILD_FULL_MAX_POINTS)

    assert full["count"] == 100_000
    assert "truncated" not in full
    assert len(full["positions"]) == 300_000
    assert len(full["radii"]) == 100_000
    assert truncated["truncated"] is True
    assert "positions" not in truncated


def test_point_cloud_build_full_default_is_unbounded_for_force_sync(monkeypatch):
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
        _BUILD_FULL_MAX_POINTS,
    )

    fake_bpy = SimpleNamespace(
        data=SimpleNamespace(pointclouds=[
            _FakePointCloud("Big", _BUILD_FULL_MAX_POINTS + 1),
        ]),
    )
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)

    h = PointCloudCategoryHandler()
    full = h.build_full()
    bounded = h.build_full(max_points=_BUILD_FULL_MAX_POINTS)

    assert full[0]["count"] == _BUILD_FULL_MAX_POINTS + 1
    assert "truncated" not in full[0]
    assert len(full[0]["positions"]) == (_BUILD_FULL_MAX_POINTS + 1) * 3
    assert bounded[0]["truncated"] is True
    assert "positions" not in bounded[0]


def test_gateway_only_bounds_point_cloud_for_initial_snapshot():
    from blender_sync.adapters.scene.bpy_scene_gateway import BpySceneGateway
    from blender_sync.adapters.scene.categories.point_cloud import (
        _BUILD_FULL_MAX_POINTS,
    )
    from tests.fakes.logger import RecordingLogger

    class FakePointCloudHandler:
        def __init__(self):
            self.calls: list[int | None] = []

        def build_full(self, max_points=None):
            self.calls.append(max_points)
            return [{"name": "Big"}]

    gateway = BpySceneGateway(RecordingLogger(), DirtyTracker())
    handler = FakePointCloudHandler()
    gateway._handlers = {CategoryKind.POINT_CLOUD: handler}

    assert gateway.build_full_snapshot() == [
        (CategoryKind.POINT_CLOUD, [{"name": "Big"}]),
    ]
    assert handler.calls == [None]

    assert gateway.build_full_snapshot(initial_snapshot=True) == [
        (CategoryKind.POINT_CLOUD, [{"name": "Big"}]),
    ]
    assert handler.calls == [None, _BUILD_FULL_MAX_POINTS]


def test_dirty_tracker_carries_volume_point_cloud():
    t = DirtyTracker()
    t.mark_volume("Volume")
    t.mark_point_cloud("PointCloud")
    snap = t.flush()
    assert "Volume" in snap.volumes
    assert "PointCloud" in snap.point_clouds
    assert t.flush().is_empty()


def test_volume_point_cloud_use_reliable_channel():
    assert CATEGORY_TO_CHANNEL[CategoryKind.VOLUME] is ChannelKind.RELIABLE
    assert CATEGORY_TO_CHANNEL[CategoryKind.POINT_CLOUD] is ChannelKind.RELIABLE


def test_vse_strip_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        vse_strip = True

    h = VSEStripCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_vse_strip_uses_reliable_channel():
    assert CATEGORY_TO_CHANNEL[CategoryKind.VSE_STRIP] is ChannelKind.RELIABLE


def test_dirty_tracker_carries_vse_strip():
    t = DirtyTracker()
    t.mark_vse_strip()
    snap = t.flush()
    assert snap.vse_strip is True
    assert t.flush().is_empty()


def test_vse_strip_collect_skipped_when_flag_clear():
    """If DirtyContext.vse_strip is False, the handler must short-circuit
    without paying the bpy import."""
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        vse_strip = False

    h = VSEStripCategoryHandler()
    assert h.collect(DirtyContext(S())) == []


def test_vse_strip_hash_dedupe():
    """Repeated identical timeline payloads must not be re-sent.
    Drives the per-scene hash cache path."""
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )

    h = VSEStripCategoryHandler()
    op = {"scene": "Scene", "active": True, "strips": []}
    d1 = h._hash_op(op)
    d2 = h._hash_op({"scene": "Scene", "active": True, "strips": []})
    assert d1 == d2
    assert d1 != h._hash_op({"scene": "Scene", "active": True,
                              "strips": [{"name": "S1"}]})


def test_vse_remote_apply_clears_hash_so_return_to_local_a_resends(monkeypatch):
    from blender_sync.adapters.scene.categories.base import DirtyContext
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )

    class S(_FakeSnap):
        vse_strip = True

    class FakeStrip:
        def __init__(self, name: str):
            self.name = name
            self.type = "COLOR"
            self.channel = 1
            self.frame_start = 1
            self.frame_final_duration = 10
            self.transform = None

    def set_timeline(scene, names):
        strips = [FakeStrip(name) for name in names]
        scene.sequence_editor = SimpleNamespace(
            show_overlay_frame=False,
            strips_all=strips,
            sequences_all=strips,
        )

    scene = _FakeVSEScene("Scene")
    set_timeline(scene, ["A"])
    _install_fake_vse_bpy(monkeypatch, [scene], scene)

    h = VSEStripCategoryHandler()
    ctx = DirtyContext(S())
    first = h.collect(ctx)
    assert first
    assert h.collect(ctx) == []

    h.apply([{"scene": "Scene", "active": False, "strips": []}])
    assert "Scene" not in h._sent_hash

    set_timeline(scene, ["A"])
    resend = h.collect(ctx)
    assert resend == first


def test_vse_apply_missing_named_scene_does_not_clear_active(monkeypatch):
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )
    from tests.fakes.logger import RecordingLogger

    active = _FakeVSEScene("Active")
    logger = RecordingLogger()
    _install_fake_vse_bpy(monkeypatch, [active], active)

    h = VSEStripCategoryHandler(logger=logger)
    h.apply([{"scene": "RenamedAway", "active": False, "strips": []}])

    assert active.clear_count == 0
    assert active.create_count == 0
    assert any(
        level == "WARN" and "RenamedAway" in text
        for level, text in logger.records
    )


def test_vse_apply_matching_scene_clears_named_scene_only(monkeypatch):
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )

    active = _FakeVSEScene("Active")
    target = _FakeVSEScene("Timeline")
    _install_fake_vse_bpy(monkeypatch, [active, target], active)

    h = VSEStripCategoryHandler()
    h.apply([{"scene": "Timeline", "active": False, "strips": []}])

    assert target.clear_count == 1
    assert active.clear_count == 0


def test_vse_apply_without_scene_key_uses_context_fallback(monkeypatch):
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )

    active = _FakeVSEScene("Active")
    _install_fake_vse_bpy(monkeypatch, [active], active)

    h = VSEStripCategoryHandler()
    h.apply([{"active": False, "strips": []}])

    assert active.clear_count == 1


def test_vse_serialize_movieclip_and_mask_refs(monkeypatch):
    from blender_sync.adapters.scene.categories import vse_strip as vsm

    class FakeStrip:
        def __init__(self, stype: str, attr: str, target):
            self.name = f"{stype}_Strip"
            self.type = stype
            self.channel = 2
            self.frame_start = 11
            self.frame_final_duration = 23
            self.transform = None
            setattr(self, attr, target)

    clip = SimpleNamespace(name="ClipData")
    mask = SimpleNamespace(name="MaskData")

    def fake_ref(value):
        return f"ref:{value.name}"

    monkeypatch.setattr(vsm._datablock_ref, "try_ref", fake_ref)

    h = vsm.VSEStripCategoryHandler()
    clip_out = h._serialize_strip(FakeStrip("MOVIECLIP", "clip", clip))
    mask_out = h._serialize_strip(FakeStrip("MASK", "mask", mask))

    assert clip_out["clip_ref"] == "ref:ClipData"
    assert clip_out["length"] == 23
    assert mask_out["mask_ref"] == "ref:MaskData"
    assert mask_out["length"] == 23


def test_vse_apply_recreates_meta_movieclip_and_mask(monkeypatch):
    from blender_sync.adapters.scene.categories import vse_strip as vsm

    clip = SimpleNamespace(name="ClipData")
    mask = SimpleNamespace(name="MaskData")
    refs = {"clip-token": clip, "mask-token": mask}
    monkeypatch.setattr(vsm._datablock_ref, "resolve_ref", refs.get)

    coll = _FakeVSECollection()
    scene = _FakeVSEScene("Scene", collection=coll)
    h = vsm.VSEStripCategoryHandler()

    h._apply_scene(None, scene, {
        "active": True,
        "strips": [
            {"type": "META", "name": "Meta", "channel": 1, "frame_start": 3},
            {
                "type": "MOVIECLIP",
                "name": "ClipStrip",
                "channel": 2,
                "frame_start": 4,
                "clip_ref": "clip-token",
            },
            {
                "type": "MASK",
                "name": "MaskStrip",
                "channel": 3,
                "frame_start": 5,
                "mask_ref": "mask-token",
            },
        ],
    })

    assert scene.clear_count == 1
    assert scene.create_count == 1
    assert coll.calls == [
        ("new_meta", "Meta", 1, 3),
        ("new_clip", "ClipStrip", clip, 2, 4),
        ("new_mask", "MaskStrip", mask, 3, 5),
    ]


def test_vse_apply_skips_unresolved_movieclip_and_mask(monkeypatch):
    from blender_sync.adapters.scene.categories import vse_strip as vsm
    from tests.fakes.logger import RecordingLogger

    monkeypatch.setattr(vsm._datablock_ref, "resolve_ref", lambda token: None)
    coll = _FakeVSECollection()
    scene = _FakeVSEScene("Scene", collection=coll)
    logger = RecordingLogger()
    h = vsm.VSEStripCategoryHandler(logger=logger)

    h._apply_scene(None, scene, {
        "active": True,
        "strips": [
            {
                "type": "MOVIECLIP",
                "name": "MissingClip",
                "channel": 1,
                "frame_start": 1,
                "clip_ref": "missing-clip",
            },
            {
                "type": "MASK",
                "name": "MissingMask",
                "channel": 2,
                "frame_start": 1,
                "mask_ref": "missing-mask",
            },
        ],
    })

    assert coll.calls == []
    warnings = [text for level, text in logger.records if level == "WARN"]
    assert any("MOVIECLIP" in text and "MissingClip" in text for text in warnings)
    assert any("MASK" in text and "MissingMask" in text for text in warnings)


def test_vse_effect_constants_match_blender_5():
    """`new_effect` enum in Blender 5 dropped TRANSFORM and OVER_DROP.
    The handler's effect-type sets must reflect that — sending an
    invalid type to a peer would raise on `new_effect` and the strip
    would silently be lost. Lock the valid set with a test."""
    from blender_sync.adapters.scene.categories import vse_strip as vsm

    # TRANSFORM and OVER_DROP must NOT appear anywhere in the effect
    # type buckets. Blender 5 supplants them with the per-strip
    # `Strip.transform` sub-struct (handled separately in serialize).
    all_effects = (
        vsm._ZERO_INPUT_EFFECTS
        | vsm._ONE_INPUT_EFFECTS
        | vsm._TWO_INPUT_EFFECTS
    )
    assert "TRANSFORM" not in all_effects
    assert "OVER_DROP" not in all_effects
    # Sanity: the documented Blender 5 enum values we care about.
    assert "COLOR" in vsm._ZERO_INPUT_EFFECTS
    assert "TEXT" in vsm._ZERO_INPUT_EFFECTS
    assert "GAUSSIAN_BLUR" in vsm._ONE_INPUT_EFFECTS
    assert "GLOW" in vsm._ONE_INPUT_EFFECTS
    assert "MULTICAM" in vsm._ONE_INPUT_EFFECTS
    assert "CROSS" in vsm._TWO_INPUT_EFFECTS
    assert "COLORMIX" in vsm._TWO_INPUT_EFFECTS


def test_vse_strip_serialize_omits_transform_legacy_props():
    """The legacy TRANSFORM strip-type and its `translate_start_x`
    family are gone in Blender 5. Make sure the handler doesn't
    reintroduce them via _TYPE_SPECIFIC."""
    from blender_sync.adapters.scene.categories import vse_strip as vsm

    assert "TRANSFORM" not in vsm._TYPE_SPECIFIC
    for fields in vsm._TYPE_SPECIFIC.values():
        for f in fields:
            assert not f.startswith("translate_start_"), (
                f"legacy field {f} leaked into _TYPE_SPECIFIC"
            )


def test_sound_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.sound import (
        SoundCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        sounds = frozenset({"BGM"})

    h = SoundCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_sound_uses_reliable_channel():
    assert CATEGORY_TO_CHANNEL[CategoryKind.SOUND] is ChannelKind.RELIABLE


def test_dirty_tracker_carries_sound():
    t = DirtyTracker()
    t.mark_sound("BGM")
    snap = t.flush()
    assert "BGM" in snap.sounds
    assert t.flush().is_empty()


def test_render_view_layer_pass_fields_cover_cryptomatte():
    """Compositor cryptomatte nodes need the per-pass enables on the
    sender's view layer to land on the peer. Lock the field list."""
    from blender_sync.adapters.scene.categories.render import (
        _VIEW_LAYER_PASS_FIELDS,
    )
    for needed in (
        "use_pass_cryptomatte_object",
        "use_pass_cryptomatte_material",
        "use_pass_cryptomatte_asset",
    ):
        assert needed in _VIEW_LAYER_PASS_FIELDS


def test_render_fields_cover_compositor_audio_flags():
    """Render-side scene flags: use_compositing / use_sequencer /
    use_audio drive the rendered output significantly. Without them
    peers render with the wrong post-pipe."""
    from blender_sync.adapters.scene.categories.render import _RENDER_FIELDS
    for needed in ("use_compositing", "use_sequencer", "use_audio"):
        assert needed in _RENDER_FIELDS


def test_compositor_serialize_emits_use_viewer_border():
    """In Blender 5 the only compositor node_tree-level prop that
    survived the GPU refactor is `use_viewer_border`. Verify the wire
    carries it and does not regress to the legacy 4.x quality/chunk
    fields (which silently no-op on 5.x)."""
    from blender_sync.adapters.scene.categories.compositor import (
        CompositorCategoryHandler,
        _TREE_FIELDS,
    )

    # Lock the field list so we don't reintroduce removed-in-5.0
    # legacy fields without a deliberate decision.
    assert _TREE_FIELDS == ("use_viewer_border",)

    class FakeTree:
        use_viewer_border = True
        nodes = ()
        links = ()

    class FakeScene:
        name = "Scene"
        use_nodes = True
        node_tree = FakeTree()

    h = CompositorCategoryHandler()
    out = h._serialize(FakeScene())
    assert len(out) == 1
    op = out[0]
    assert op["use_nodes"] is True
    assert op["tree_props"]["use_viewer_border"] is True


def test_view3d_uses_fast_channel():
    """3D-view shading is interactive UI state — losing the occasional
    flip is fine. Wire on the FAST channel like transform."""
    assert CATEGORY_TO_CHANNEL[CategoryKind.VIEW3D] is ChannelKind.FAST


def test_view3d_handler_no_bpy_graceful():
    from blender_sync.adapters.scene.categories.view3d import (
        View3DCategoryHandler,
    )
    from blender_sync.adapters.scene.categories.base import DirtyContext

    class S(_FakeSnap):
        view3d = True

    h = View3DCategoryHandler()
    assert h.collect(DirtyContext(S())) == []
    assert h.build_full() == []


def test_dirty_tracker_carries_view3d():
    t = DirtyTracker()
    t.mark_view3d()
    snap = t.flush()
    assert snap.view3d is True
    assert t.flush().is_empty()


def test_modifier_geometry_nodes_id_props_round_trip():
    """Geometry Nodes modifier instances hide their input bindings in
    ID-props (`Input_<n>`, `..._attribute_name`, `..._use_attribute`).
    Walker must pull these via `.keys()` because dir() doesn't list
    them."""
    from blender_sync.adapters.scene.categories.modifier import (
        ModifierCategoryHandler,
    )

    class FakeNodesMod:
        name = "GeometryNodes"
        type = "NODES"
        show_viewport = True

        _store = {
            "Input_2": 0.5,
            "Input_2_use_attribute": False,
            "Input_2_attribute_name": "density",
            "Input_3": 4,
        }

        def keys(self): return list(self._store.keys())
        def __getitem__(self, k): return self._store[k]

    h = ModifierCategoryHandler()
    out = h._serialize_modifier(FakeNodesMod())
    assert out["type"] == "NODES"
    ip = out["id_props"]
    assert ip["Input_2"] == 0.5
    assert ip["Input_2_use_attribute"] is False
    assert ip["Input_2_attribute_name"] == "density"
    assert ip["Input_3"] == 4


def test_sound_serialize_picks_filepath():
    from blender_sync.adapters.scene.categories.sound import (
        SoundCategoryHandler,
    )

    class FakeSound:
        name = "BGM"
        filepath = "//audio/bgm.wav"
        use_memory_cache = True
        use_mono = False

    h = SoundCategoryHandler()
    out = h._serialize(FakeSound())
    assert out["name"] == "BGM"
    assert out["props"]["filepath"] == "//audio/bgm.wav"
    assert out["props"]["use_memory_cache"] is True
    assert out["props"]["use_mono"] is False


def test_vse_apply_blacklist_rejects_input_keys():
    """`input_1` / `input_2` are wire-only; the apply loop must not
    setattr them onto the strip (they're populated via the new_effect
    constructor in the second pass)."""
    from blender_sync.adapters.scene.categories.vse_strip import (
        VSEStripCategoryHandler,
    )

    blacklist = VSEStripCategoryHandler._APPLY_BLACKLIST
    assert "input_1" in blacklist
    assert "input_2" in blacklist
    assert "length" in blacklist
    assert "clip_ref" in blacklist
    assert "mask_ref" in blacklist
    assert "transform" in blacklist  # handled via dedicated branch


def test_pose_serializes_custom_shape_fields_when_present():
    """Verifies the custom-shape fields serialize through the duck-typed
    fallback path. Catches typos in the wire field names."""
    from blender_sync.adapters.scene.categories.pose import PoseCategoryHandler

    class FakeColor:
        palette = "DEFAULT"

    class FakePB:
        name = "Bone"
        location = (0, 0, 0)
        scale = (1, 1, 1)
        rotation_mode = "QUATERNION"
        rotation_quaternion = (1, 0, 0, 0)
        color = FakeColor()
        custom_shape = None
        custom_shape_scale_xyz = (2.0, 3.0, 4.0)
        custom_shape_translation = (0.5, 0.0, 0.0)
        custom_shape_rotation_euler = (0.0, 0.0, 0.0)
        use_custom_shape_bone_size = False
        custom_shape_wire_width = 1.5
        custom_shape_transform = None
        constraints = ()

    class FakePose:
        bones = (FakePB(),)

    class FakeArm:
        name = "Armature"
        type = "ARMATURE"
        pose = FakePose()

    h = PoseCategoryHandler()
    out = h._serialize(FakeArm())
    bone = out["bones"][0]
    assert bone["custom_shape_scale_xyz"] == [2.0, 3.0, 4.0]
    assert bone["custom_shape_translation"] == [0.5, 0.0, 0.0]
    assert bone["use_custom_shape_bone_size"] is False
    assert bone["custom_shape_wire_width"] == 1.5
    # Cleared custom_shape (None) must be encoded as the empty-string
    # sentinel so peers can clear theirs in turn — otherwise unsetting
    # a widget never propagates and peers stay stuck on the old shape.
    assert bone["custom_shape"] == ""
    assert bone["custom_shape_transform"] == ""


def test_modifier_serialize_walks_nested_settings():
    """Cloth / SoftBody / Fluid hide their interesting state in nested
    settings sub-structs. The walker must flatten those into a `nested`
    dict, otherwise peers receive an empty modifier and sim diverges."""
    from blender_sync.adapters.scene.categories.modifier import (
        ModifierCategoryHandler,
    )

    class FakeEffectorWeights:
        gravity = 1.0
        wind = 0.5
        vortex = 0.0
        rna_type = "SHOULD_NOT_LEAK"

    class FakeClothSettings:
        # Subset of ClothSettings — primitives only.
        mass = 0.3
        air_damping = 1.0
        bending_stiffness = 0.5
        tension_stiffness = 15.0
        effector_weights = FakeEffectorWeights()
        rna_type = "SHOULD_NOT_LEAK"

    class FakeClothCollisionSettings:
        use_collision = True
        distance_min = 0.015
        bl_rna = "SHOULD_NOT_LEAK"

    class FakeMod:
        name = "Cloth"
        type = "CLOTH"
        show_viewport = True
        settings = FakeClothSettings()
        collision_settings = FakeClothCollisionSettings()

    h = ModifierCategoryHandler()
    out = h._serialize_modifier(FakeMod())
    assert out["name"] == "Cloth"
    assert out["type"] == "CLOTH"
    assert "nested" in out
    inner = out["nested"]
    assert inner["settings"]["mass"] == 0.3
    assert inner["settings"]["tension_stiffness"] == 15.0
    assert inner["collision_settings"]["use_collision"] is True
    assert inner["collision_settings"]["distance_min"] == 0.015
    # Internal RNA fields must not leak through.
    assert "rna_type" not in inner["settings"]
    assert "bl_rna" not in inner["collision_settings"]
    # effector_weights must be picked up via the deep walk; without it
    # peers won't reproduce gravity / wind / vortex weighting.
    assert "__deep__" in inner["settings"]
    deep = inner["settings"]["__deep__"]["effector_weights"]
    assert deep["gravity"] == 1.0
    assert deep["wind"] == 0.5
    assert "rna_type" not in deep


def test_particle_settings_serializes_refs_and_deep():
    """ParticleSettings hides three classes of state we need to sync:
      1. Object / Collection datablock pointers (instance, collision).
      2. effector_weights — a sub-struct of force-field weighting.
      3. force_field_1 / force_field_2 — FieldSettings sub-structs that
         are auto-allocated (never None) and not datablock pointers.

    Without (3) peers see the wrong per-particle field type and hair
    physics diverges. Encoded in the same `deep` slot as effector_weights.
    """
    from blender_sync.adapters.scene.categories import particle as pmod

    class FakeEW:
        gravity = 0.5
        wind = 1.0

    class FakeFieldSettings:
        type = "VORTEX"
        strength = 4.0
        flow = 1.0
        seed = 5

    class FakeSettings:
        name = "ParticleSettings"
        count = 100
        child_type = "INTERPOLATED"
        child_nbr = 4
        rendered_child_count = 50
        use_hair_dynamics = True
        hair_step = 5
        # Real datablock pointers — passing None to exercise the
        # explicit-clear path. In live Blender these would be Object /
        # Collection instances and try_ref would emit a sentinel.
        instance_object = None
        instance_collection = None
        collision_collection = None
        # Force-field sub-structs are auto-allocated and never None.
        force_field_1 = FakeFieldSettings()
        force_field_2 = FakeFieldSettings()
        effector_weights = FakeEW()

    out = pmod._serialize_settings(FakeSettings())
    assert out["name"] == "ParticleSettings"
    p = out["props"]
    assert p["count"] == 100
    assert p["child_type"] == "INTERPOLATED"
    assert p["child_nbr"] == 4
    assert p["rendered_child_count"] == 50
    assert p["use_hair_dynamics"] is True
    assert p["hair_step"] == 5
    # refs: each real datablock pointer encoded as "" since the fake
    # holds None on each.
    assert out["refs"]["instance_object"] == ""
    assert out["refs"]["instance_collection"] == ""
    assert out["refs"]["collision_collection"] == ""
    # deep walk: effector_weights primitives.
    assert out["deep"]["effector_weights"]["gravity"] == 0.5
    assert out["deep"]["effector_weights"]["wind"] == 1.0
    # deep walk: per-particle force fields. The earlier-rejected first
    # cut treated these as datablock refs, which silently dropped them
    # because FieldSettings is a sub-struct, not an ID.
    assert out["deep"]["force_field_1"]["type"] == "VORTEX"
    assert out["deep"]["force_field_1"]["strength"] == 4.0
    assert out["deep"]["force_field_2"]["type"] == "VORTEX"
    # The deep structs must NOT also leak into props.
    assert "effector_weights" not in p
    assert "force_field_1" not in p
    assert "force_field_2" not in p


def test_modifier_serialize_handles_no_nested_settings():
    """A modifier with no physics struct shouldn't grow a `nested` key."""
    from blender_sync.adapters.scene.categories.modifier import (
        ModifierCategoryHandler,
    )

    class FakeMod:
        name = "Subsurf"
        type = "SUBSURF"
        levels = 2
        render_levels = 3

    h = ModifierCategoryHandler()
    out = h._serialize_modifier(FakeMod())
    assert "nested" not in out
    assert out["props"]["levels"] == 2


def test_shape_keys_serialize_includes_interpolation():
    """Ensures shape-key handler picks up `interpolation` (Blender 4 ease
    curve enum) so peers reproduce non-linear blends."""
    from blender_sync.adapters.scene.categories.shape_keys import (
        ShapeKeysCategoryHandler,
    )

    class FakeKBDataList(list):
        def foreach_get(self, key, buf):
            for i in range(len(buf)):
                buf[i] = 0.0

    class FakeKBData:
        co = (0.0, 0.0, 0.0)

    class FakeKB:
        name = "Smile"
        value = 0.5
        mute = False
        slider_min = 0.0
        slider_max = 1.0
        vertex_group = ""
        relative_key = None
        interpolation = "KEY_BSPLINE"

        def __init__(self):
            self.data = FakeKBDataList([FakeKBData()])

    class FakeKeys:
        use_relative = True
        key_blocks = (FakeKB(),)

    class FakeData:
        shape_keys = FakeKeys()

    class FakeObj:
        name = "Cube"
        data = FakeData()

    h = ShapeKeysCategoryHandler()
    out = h._serialize(FakeObj())
    blocks = out["blocks"]
    assert blocks[0]["interpolation"] == "KEY_BSPLINE"
    assert blocks[0]["vertex_group"] == ""

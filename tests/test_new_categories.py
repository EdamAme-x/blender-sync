"""Tests for newly added sync categories: Camera, Light, MaterialSlots,
plus the SyncFilters.enabled_categories() central source-of-truth.
"""
from __future__ import annotations

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
    volume=False, point_cloud=False,
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
    render = False
    compositor = False
    scene_world = False


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


def test_point_cloud_build_full_truncates_oversize():
    from blender_sync.adapters.scene.categories.point_cloud import (
        PointCloudCategoryHandler,
        _BUILD_FULL_MAX_POINTS,
    )

    class FakePoints:
        def __init__(self, n): self.n = n
        def __len__(self): return self.n

    class FakePC:
        def __init__(self, name, n):
            self.name = name
            self.points = FakePoints(n)

    h = PointCloudCategoryHandler()
    out = h._serialize(FakePC("Big", _BUILD_FULL_MAX_POINTS + 1),
                       max_points=_BUILD_FULL_MAX_POINTS)
    assert out["truncated"] is True
    assert "positions" not in out
    assert "radii" not in out


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
    # Empty custom_shape (None) should not be encoded as a sentinel ref.
    assert "custom_shape" not in bone


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

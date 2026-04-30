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

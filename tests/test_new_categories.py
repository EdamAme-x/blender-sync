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
    volume=False, point_cloud=False, vse_strip=False,
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
    vse_strip = False
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

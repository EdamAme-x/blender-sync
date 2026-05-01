from __future__ import annotations

from typing import Any, Iterable

from ...domain.entities import CategoryKind
from ...domain.policies.dirty_tracker import DirtyTracker
from ...domain.ports import ILogger, ISceneGateway
from .categories import _datablock_ref, _nodetree
from .categories.animation import AnimationCategoryHandler
from .categories.armature import ArmatureCategoryHandler
from .categories.base import DirtyContext
from .categories.camera import CameraCategoryHandler
from .categories.collection import CollectionCategoryHandler
from .categories.compositor import CompositorCategoryHandler
from .categories.constraints import ConstraintsCategoryHandler
from .categories.curve import CurveCategoryHandler
from .categories.deletion import DeletionCategoryHandler
from .categories.grease_pencil import GreasePencilCategoryHandler
from .categories.image import ImageCategoryHandler
from .categories.lattice import LatticeCategoryHandler
from .categories.metaball import MetaballCategoryHandler
from .categories.node_group import NodeGroupCategoryHandler
from .categories.particle import ParticleCategoryHandler
from .categories.point_cloud import (
    PointCloudCategoryHandler,
    _BUILD_FULL_MAX_POINTS,
)
from .categories.sound import SoundCategoryHandler
from .categories.texture import TextureCategoryHandler
from .categories.view3d import View3DCategoryHandler
from .categories.volume import VolumeCategoryHandler
from .categories.vse_strip import VSEStripCategoryHandler
from .categories.light import LightCategoryHandler
from .categories.material import MaterialCategoryHandler
from .categories.material_slots import MaterialSlotsCategoryHandler
from .categories.mesh import MeshCategoryHandler
from .categories.modifier import ModifierCategoryHandler
from .categories.pose import PoseCategoryHandler
from .categories.rename import RenameCategoryHandler
from .categories.render import RenderCategoryHandler
from .categories.scene_world import SceneWorldCategoryHandler
from .categories.shape_keys import ShapeKeysCategoryHandler
from .categories.transform import TransformCategoryHandler
from .categories.visibility import VisibilityCategoryHandler


class BpySceneGateway(ISceneGateway):
    """Bridges Blender's bpy API to the Domain ISceneGateway port.

    Responsibilities:
      - Hook depsgraph_update_post and msgbus to populate DirtyTracker.
      - Track edit-mode transitions and visibility deltas.
      - Dispatch collect/apply/build_full to the registered category
        handlers via a single CategoryKind -> handler dict.

    Adding a new category requires only:
      1. Add CategoryKind enum entry + channel mapping.
      2. Create a handler with collect/apply/build_full(ctx).
      3. Register it in self._handlers below.
    """

    # Categories that require a non-empty DirtyContext to produce ops.
    _CTX_DRIVEN = {
        CategoryKind.TRANSFORM,
        CategoryKind.VISIBILITY,
        CategoryKind.MATERIAL,
        CategoryKind.MATERIAL_SLOTS,
        CategoryKind.MODIFIER,
        CategoryKind.MESH,
        CategoryKind.CAMERA,
        CategoryKind.LIGHT,
        CategoryKind.COLLECTION,
        CategoryKind.ANIMATION,
        CategoryKind.IMAGE,
    }

    def __init__(self, logger: ILogger, tracker: DirtyTracker) -> None:
        self._logger = logger
        self._tracker = tracker
        self._applying_remote = False
        self._installed = False

        self._ref_retry_queue = _datablock_ref.ReferenceResolutionQueue()

        # Ordered to satisfy dependency chains on the receiver side:
        #   image  -> material -> material_slots -> mesh
        #   armature -> pose, shape_keys
        #   collection -> object visibility
        # `apply_ops` is dispatched per-category so within a tick the
        # send order also drives the receiver's apply order.
        self._handlers: dict[CategoryKind, Any] = {
            # Tier 1: foundational data blocks referenced by others
            CategoryKind.IMAGE: ImageCategoryHandler(),
            CategoryKind.SOUND: SoundCategoryHandler(),
            CategoryKind.TEXTURE: TextureCategoryHandler(),
            CategoryKind.NODE_GROUP: NodeGroupCategoryHandler(),
            CategoryKind.ARMATURE: ArmatureCategoryHandler(),
            CategoryKind.MATERIAL: MaterialCategoryHandler(),
            # Tier 2: object-side, depend on Tier 1
            CategoryKind.TRANSFORM: TransformCategoryHandler(),
            CategoryKind.MATERIAL_SLOTS: MaterialSlotsCategoryHandler(),
            CategoryKind.MODIFIER: ModifierCategoryHandler(
                retry_queue=self._ref_retry_queue,
            ),
            CategoryKind.CONSTRAINTS: ConstraintsCategoryHandler(),
            CategoryKind.MESH: MeshCategoryHandler(),
            CategoryKind.SHAPE_KEYS: ShapeKeysCategoryHandler(),
            CategoryKind.POSE: PoseCategoryHandler(),
            CategoryKind.VISIBILITY: VisibilityCategoryHandler(),
            CategoryKind.COLLECTION: CollectionCategoryHandler(),
            CategoryKind.CURVE: CurveCategoryHandler(),
            CategoryKind.GREASE_PENCIL: GreasePencilCategoryHandler(),
            CategoryKind.LATTICE: LatticeCategoryHandler(),
            CategoryKind.METABALL: MetaballCategoryHandler(),
            CategoryKind.VOLUME: VolumeCategoryHandler(),
            CategoryKind.POINT_CLOUD: PointCloudCategoryHandler(),
            CategoryKind.PARTICLE: ParticleCategoryHandler(),
            # Tier 3: scene-level singletons
            CategoryKind.RENDER: RenderCategoryHandler(),
            CategoryKind.COMPOSITOR: CompositorCategoryHandler(),
            CategoryKind.SCENE: SceneWorldCategoryHandler(),
            CategoryKind.CAMERA: CameraCategoryHandler(),
            CategoryKind.LIGHT: LightCategoryHandler(),
            CategoryKind.ANIMATION: AnimationCategoryHandler(),
            CategoryKind.VSE_STRIP: VSEStripCategoryHandler(),
            CategoryKind.VIEW3D: View3DCategoryHandler(),
            # Tier 4: maintenance ops — must run last so deletion/rename
            # don't trip up references in earlier tiers.
            CategoryKind.RENAME: RenameCategoryHandler(),
            CategoryKind.DELETION: DeletionCategoryHandler(),
        }

        self._depsgraph_handler = self._make_depsgraph_handler()
        self._mode_state: dict[str, str] = {}
        self._msgbus_owner = object()
        self._prev_visibility: dict[str, tuple[bool, bool, bool]] = {}
        # Reverse lookups so the depsgraph handler can mark a Key/Action
        # update in O(1) instead of scanning bpy.data each call.
        self._shape_key_to_owner: dict[str, str] = {}
        self._action_to_users: dict[str, set[tuple[str, str]]] = {}
        self._cleanup_counter = 0
        self._cleanup_interval = 600

    # --- Domain port ---------------------------------------------------

    def is_applying_remote(self) -> bool:
        return self._applying_remote

    def set_applying_remote(self, value: bool) -> None:
        self._applying_remote = value

    def install_change_listeners(self) -> None:
        if self._installed:
            return
        try:
            import bpy
        except ImportError:
            return
        try:
            bpy.app.handlers.depsgraph_update_post.append(self._depsgraph_handler)
            self._subscribe_msgbus(bpy)
            self._installed = True
            self._logger.info("scene listeners installed")
        except Exception as exc:
            self._logger.error("install_change_listeners failed: %s", exc)

    def uninstall_change_listeners(self) -> None:
        if not self._installed:
            return
        try:
            import bpy
        except ImportError:
            return
        try:
            if self._depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.remove(self._depsgraph_handler)
            try:
                bpy.msgbus.clear_by_owner(self._msgbus_owner)
            except Exception:
                pass
        except Exception as exc:
            self._logger.warning("uninstall failed: %s", exc)
        finally:
            self._installed = False

    def collect_dirty_ops(
        self, categories: Iterable[CategoryKind]
    ) -> list[tuple[CategoryKind, list[dict[str, Any]]]]:
        snapshot = self._tracker.flush()
        ctx = DirtyContext(snapshot)
        cats = set(categories)
        out: list[tuple[CategoryKind, list[dict[str, Any]]]] = []

        # Iterate in `_handlers` definition order so receivers see ops
        # in a dependency-aware sequence (e.g. images before materials,
        # materials before material_slots, material_slots before mesh).
        for category, handler in self._handlers.items():
            if category not in cats:
                continue
            if not self._has_dirty_for(category, snapshot):
                continue
            try:
                ops = handler.collect(ctx)
            except Exception as exc:
                self._logger.error("collect failed for %s: %s", category, exc)
                continue
            if ops:
                out.append((category, ops))
        return out

    def _has_dirty_for(self, category: CategoryKind, snap) -> bool:
        if category is CategoryKind.TRANSFORM:
            return bool(snap.objects_transform)
        if category is CategoryKind.VISIBILITY:
            return bool(snap.objects_visibility)
        if category is CategoryKind.MATERIAL:
            return bool(snap.materials)
        if category is CategoryKind.MATERIAL_SLOTS:
            return bool(snap.objects_transform)  # piggyback on object updates
        if category is CategoryKind.MODIFIER:
            return bool(snap.modifiers)
        if category is CategoryKind.MESH:
            return bool(snap.meshes_committed) or bool(snap.meshes_editing)
        if category is CategoryKind.RENDER:
            return snap.render
        if category is CategoryKind.COMPOSITOR:
            return snap.compositor
        if category is CategoryKind.SCENE:
            return snap.scene_world
        if category is CategoryKind.CAMERA:
            return bool(snap.cameras)
        if category is CategoryKind.LIGHT:
            return bool(snap.lights)
        if category is CategoryKind.COLLECTION:
            return bool(snap.collections)
        if category is CategoryKind.ANIMATION:
            return bool(snap.animations)
        if category is CategoryKind.IMAGE:
            return bool(snap.images)
        if category is CategoryKind.DELETION:
            return True
        if category is CategoryKind.RENAME:
            return True
        if category is CategoryKind.ARMATURE:
            return bool(snap.armatures)
        if category is CategoryKind.POSE:
            return bool(snap.poses)
        if category is CategoryKind.SHAPE_KEYS:
            return bool(snap.shape_keys)
        if category is CategoryKind.CONSTRAINTS:
            # Constraints piggyback on transform dirty (any object update
            # could include a constraint edit).
            return bool(snap.objects_transform)
        if category is CategoryKind.CURVE:
            return bool(snap.curves)
        if category is CategoryKind.GREASE_PENCIL:
            return bool(snap.grease_pencils)
        if category is CategoryKind.PARTICLE:
            return bool(snap.particles)
        if category is CategoryKind.NODE_GROUP:
            return bool(snap.node_groups)
        if category is CategoryKind.TEXTURE:
            return bool(snap.textures)
        if category is CategoryKind.LATTICE:
            return bool(snap.lattices)
        if category is CategoryKind.METABALL:
            return bool(snap.metaballs)
        if category is CategoryKind.VOLUME:
            return bool(snap.volumes)
        if category is CategoryKind.POINT_CLOUD:
            return bool(snap.point_clouds)
        if category is CategoryKind.VSE_STRIP:
            return bool(getattr(snap, "vse_strip", False))
        if category is CategoryKind.SOUND:
            return bool(getattr(snap, "sounds", frozenset()))
        if category is CategoryKind.VIEW3D:
            return bool(getattr(snap, "view3d", False))
        return False

    def apply_ops(self, category: CategoryKind, ops: list[dict[str, Any]]) -> None:
        handler = self._handlers.get(category)
        if handler is None:
            self._logger.debug("apply_ops: unhandled category %s", category)
            return
        try:
            handler.apply(ops)
        except Exception as exc:
            self._logger.error("apply failed for %s: %s", category, exc)

    def build_full_snapshot(
        self, *, initial_snapshot: bool = False,
    ) -> list[tuple[CategoryKind, list[dict[str, Any]]]]:
        out: list[tuple[CategoryKind, list[dict[str, Any]]]] = []
        for category, handler in self._handlers.items():
            try:
                if initial_snapshot and category is CategoryKind.POINT_CLOUD:
                    ops = handler.build_full(max_points=_BUILD_FULL_MAX_POINTS)
                else:
                    ops = handler.build_full()
            except Exception as exc:
                self._logger.error("build_full failed for %s: %s", category, exc)
                continue
            if ops:
                out.append((category, ops))
        return out

    # --- bpy hooks -----------------------------------------------------

    def _subscribe_msgbus(self, bpy) -> None:
        owner = self._msgbus_owner

        def make_cb(mark):
            def _cb():
                if not self._applying_remote:
                    mark()
            return _cb

        try:
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.RenderSettings, "engine"),
                owner=owner, args=(), notify=make_cb(self._tracker.mark_render),
            )
        except Exception:
            pass
        for prop in ("resolution_x", "resolution_y", "fps",
                     "frame_start", "frame_end"):
            try:
                bpy.msgbus.subscribe_rna(
                    key=(bpy.types.RenderSettings, prop),
                    owner=owner, args=(),
                    notify=make_cb(self._tracker.mark_render),
                )
            except Exception:
                pass
        try:
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.Scene, "use_nodes"),
                owner=owner, args=(),
                notify=make_cb(self._tracker.mark_compositor),
            )
        except Exception:
            pass

        # Sound property toggles do not flow through depsgraph reliably
        # (Sound is a leaf ID with no evaluated graph involvement). Hook
        # them here so use_memory_cache / use_mono edits propagate. The
        # callback can't see *which* Sound changed, so we mark every
        # current Sound dirty — collect() then sends only the ones whose
        # serialized form differs (the dirty set is a hint, not a diff).
        sound_t = getattr(bpy.types, "Sound", None)
        if sound_t is not None:
            for prop in ("use_memory_cache", "use_mono"):
                try:
                    bpy.msgbus.subscribe_rna(
                        key=(sound_t, prop),
                        owner=owner, args=(),
                        notify=make_cb(self._mark_all_sounds),
                    )
                except Exception:
                    pass

        self._subscribe_view3d_msgbus(bpy)

    def _mark_all_sounds(self) -> None:
        try:
            import bpy
        except ImportError:
            return
        sounds = getattr(bpy.data, "sounds", None)
        if sounds is None:
            return
        for snd in sounds:
            self._tracker.mark_sound(snd.name)

    # 3D-view shading flips (SOLID / MATERIAL / RENDERED, scene-lights
    # toggle, etc.) flow through msgbus on the View3DShading struct.
    # Without subscribing to it the receiver only learns of shading
    # changes when something else triggers the dirty path.
    def _subscribe_view3d_msgbus(self, bpy) -> None:
        owner = self._msgbus_owner
        shading_t = getattr(bpy.types, "View3DShading", None)
        if shading_t is None:
            return
        for prop in (
            "type", "light", "color_type",
            "use_scene_lights", "use_scene_world",
            "use_scene_lights_render", "use_scene_world_render",
            "show_xray", "show_shadows", "show_cavity",
        ):
            try:
                bpy.msgbus.subscribe_rna(
                    key=(shading_t, prop),
                    owner=owner, args=(),
                    notify=self._notify_view3d,
                )
            except Exception:
                pass

    def _notify_view3d(self) -> None:
        if self._applying_remote:
            return
        self._tracker.mark_view3d()

    def _make_depsgraph_handler(self):
        gateway = self

        def _handler(scene, depsgraph=None):
            if gateway._applying_remote:
                return
            try:
                import bpy
            except ImportError:
                return

            dg = depsgraph
            if dg is None:
                try:
                    dg = bpy.context.evaluated_depsgraph_get()
                except Exception:
                    return

            try:
                for update in dg.updates:
                    obj = update.id
                    obj_name = getattr(obj, "name", None)
                    if obj_name is None:
                        continue
                    if isinstance(obj, bpy.types.Object):
                        if getattr(update, "is_updated_transform", False):
                            gateway._tracker.mark_transform(obj_name)
                            gateway._track_visibility(obj, obj_name)
                        if getattr(update, "is_updated_geometry", False):
                            if obj.mode != "EDIT":
                                gateway._tracker.mark_mesh_committed(obj_name)
                            else:
                                gateway._tracker.mark_mesh_editing(obj_name)
                        if hasattr(obj, "modifiers") and len(obj.modifiers) > 0:
                            gateway._tracker.mark_modifier(obj_name, "")
                        if getattr(obj, "animation_data", None) is not None:
                            gateway._tracker.mark_animation(f"object:{obj_name}")
                        data = getattr(obj, "data", None)
                        if data is not None:
                            data_name = getattr(data, "name", None)
                            if data_name:
                                if isinstance(data, bpy.types.Camera):
                                    gateway._tracker.mark_camera(data_name)
                                elif isinstance(data, bpy.types.Light):
                                    gateway._tracker.mark_light(data_name)
                                elif isinstance(data, bpy.types.Armature):
                                    gateway._tracker.mark_armature(data_name)
                                elif isinstance(data, bpy.types.Curve):
                                    gateway._tracker.mark_curve(data_name)
                                elif isinstance(data, bpy.types.Lattice):
                                    gateway._tracker.mark_lattice(data_name)
                                elif isinstance(data, bpy.types.MetaBall):
                                    gateway._tracker.mark_metaball(data_name)
                                elif (
                                    getattr(bpy.types, "Volume", None) is not None
                                    and isinstance(data, bpy.types.Volume)
                                ):
                                    gateway._tracker.mark_volume(data_name)
                                elif (
                                    getattr(bpy.types, "PointCloud", None) is not None
                                    and isinstance(data, bpy.types.PointCloud)
                                ):
                                    gateway._tracker.mark_point_cloud(data_name)
                                else:
                                    gp_v3 = getattr(bpy.types, "GreasePencilv3", None)
                                    gp_classic = getattr(bpy.types, "GreasePencil", None)
                                    if (
                                        (gp_v3 is not None and isinstance(data, gp_v3))
                                        or (gp_classic is not None and isinstance(data, gp_classic))
                                    ):
                                        gateway._tracker.mark_grease_pencil(data_name)
                            sk = getattr(data, "shape_keys", None)
                            if sk is not None:
                                gateway._tracker.mark_shape_keys(obj.name)
                        if obj.type == "ARMATURE":
                            gateway._tracker.mark_pose(obj.name)
                        if hasattr(obj, "particle_systems") and obj.particle_systems:
                            gateway._tracker.mark_particle(obj.name)
                    elif isinstance(obj, bpy.types.Material):
                        gateway._tracker.mark_material(obj_name)
                        if getattr(obj, "animation_data", None) is not None:
                            gateway._tracker.mark_animation(f"material:{obj_name}")
                    elif isinstance(obj, bpy.types.Camera):
                        gateway._tracker.mark_camera(obj_name)
                        if getattr(obj, "animation_data", None) is not None:
                            gateway._tracker.mark_animation(f"camera:{obj_name}")
                    elif isinstance(obj, bpy.types.Light):
                        gateway._tracker.mark_light(obj_name)
                        if getattr(obj, "animation_data", None) is not None:
                            gateway._tracker.mark_animation(f"light:{obj_name}")
                    elif isinstance(obj, bpy.types.Collection):
                        gateway._tracker.mark_collection(obj_name)
                    elif isinstance(obj, bpy.types.Image):
                        gateway._tracker.mark_image(obj_name)
                    elif (
                        getattr(bpy.types, "Sound", None) is not None
                        and isinstance(obj, bpy.types.Sound)
                    ):
                        gateway._tracker.mark_sound(obj_name)
                    elif isinstance(obj, bpy.types.Armature):
                        gateway._tracker.mark_armature(obj_name)
                    elif isinstance(obj, bpy.types.Curve):
                        gateway._tracker.mark_curve(obj_name)
                    elif isinstance(obj, bpy.types.Lattice):
                        gateway._tracker.mark_lattice(obj_name)
                    elif isinstance(obj, bpy.types.MetaBall):
                        gateway._tracker.mark_metaball(obj_name)
                    elif (
                        getattr(bpy.types, "Volume", None) is not None
                        and isinstance(obj, bpy.types.Volume)
                    ):
                        gateway._tracker.mark_volume(obj_name)
                    elif (
                        getattr(bpy.types, "PointCloud", None) is not None
                        and isinstance(obj, bpy.types.PointCloud)
                    ):
                        gateway._tracker.mark_point_cloud(obj_name)
                    elif isinstance(obj, bpy.types.NodeTree):
                        gateway._tracker.mark_node_group(obj_name)
                        # Transitive: nested NodeGroups must also be sent
                        # so the receiver can rebuild the dependency chain.
                        try:
                            for nested in _nodetree.collect_referenced_node_groups(obj):
                                gateway._tracker.mark_node_group(nested)
                        except Exception as exc:
                            gateway._logger.debug(
                                "transitive node_group walk failed: %s", exc,
                            )
                    elif isinstance(obj, bpy.types.Texture):
                        gateway._tracker.mark_texture(obj_name)
                    elif isinstance(obj, bpy.types.Key):
                        # Reverse lookup populated by the live-name pass
                        # below. O(1) instead of O(N) per Key update.
                        owner_name = gateway._shape_key_to_owner.get(obj_name)
                        if owner_name:
                            gateway._tracker.mark_shape_keys(owner_name)
                    elif isinstance(obj, bpy.types.Action):
                        # Reverse lookup keyed by action name; the live
                        # pass below keeps it fresh.
                        users = gateway._action_to_users.get(obj_name)
                        if users:
                            for kind, owner_name in users:
                                gateway._tracker.mark_animation(
                                    f"{kind}:{owner_name}"
                                )
                    elif isinstance(obj, bpy.types.World):
                        gateway._tracker.mark_scene_world()
                        if getattr(obj, "animation_data", None) is not None:
                            gateway._tracker.mark_animation(f"world:{obj_name}")
                    elif isinstance(obj, bpy.types.Scene):
                        gateway._tracker.mark_scene_world()
                        # VSE strip changes route through Scene updates;
                        # the strip handler itself hashes content so a
                        # false-positive here just becomes a no-op send.
                        gateway._tracker.mark_vse_strip()
            except Exception as exc:
                gateway._logger.debug("depsgraph iter failed: %s", exc)

            try:
                live_names: set[str] = set()
                # Rebuild reverse lookups while we already have the
                # objects in hand (cheap; same loop as other live work).
                fresh_sk: dict[str, str] = {}
                fresh_action: dict[str, set[tuple[str, str]]] = {}

                def _record_action_user(kind: str, ad, owner_name: str) -> None:
                    if ad is not None and ad.action is not None:
                        fresh_action.setdefault(ad.action.name, set()).add(
                            (kind, owner_name)
                        )

                for obj in scene.objects:
                    live_names.add(obj.name)
                    prev = gateway._mode_state.get(obj.name)
                    cur = obj.mode
                    if prev == "EDIT" and cur != "EDIT":
                        gateway._tracker.mark_mesh_committed(obj.name)
                    gateway._mode_state[obj.name] = cur
                    gateway._track_visibility(obj, obj.name)

                    data = getattr(obj, "data", None)
                    if data is not None:
                        sk = getattr(data, "shape_keys", None)
                        sk_name = getattr(sk, "name", None) if sk else None
                        if sk_name:
                            fresh_sk[sk_name] = obj.name
                    _record_action_user(
                        "object", getattr(obj, "animation_data", None), obj.name
                    )

                # Walk other animatable data block collections once so
                # Action edits can fan out without per-tick linear scans.
                for kind, attr in (
                    ("material", "materials"),
                    ("world", "worlds"),
                    ("camera", "cameras"),
                    ("light", "lights"),
                    ("armature", "armatures"),
                ):
                    coll = getattr(bpy.data, attr, None)
                    if coll is None:
                        continue
                    for d in coll:
                        _record_action_user(
                            kind, getattr(d, "animation_data", None), d.name
                        )

                gateway._shape_key_to_owner = fresh_sk
                gateway._action_to_users = fresh_action

                gateway._cleanup_counter += 1
                if gateway._cleanup_counter >= gateway._cleanup_interval:
                    gateway._cleanup_counter = 0
                    for stale in [n for n in gateway._mode_state if n not in live_names]:
                        gateway._mode_state.pop(stale, None)
                    for stale in [n for n in gateway._prev_visibility if n not in live_names]:
                        gateway._prev_visibility.pop(stale, None)
            except Exception:
                pass

        return _handler

    def _track_visibility(self, obj, obj_name: str) -> None:
        try:
            cur = (
                bool(obj.hide_viewport),
                bool(obj.hide_render),
                bool(obj.hide_select),
            )
        except Exception:
            return
        prev = self._prev_visibility.get(obj_name)
        if prev != cur:
            self._prev_visibility[obj_name] = cur
            self._tracker.mark_visibility(obj_name)

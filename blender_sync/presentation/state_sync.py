"""Bridge between SyncRuntime sessions and Blender's PropertyGroup state.

Owns the responsibility of:
  - Reflecting session/status updates onto bpy.types.Scene.blender_sync_state
  - Reading Sync Filters and Preferences from bpy and producing pure
    SyncFilters / TransportConfig / SignalingConfig values

Domain stays clean of any bpy reference; this module is the only place in
presentation/ that touches both bpy and Domain entities directly.
"""
from __future__ import annotations

from typing import Any, Callable

from ..domain.entities import (
    ConflictResolutionConfig,
    IceServer,
    MeshSyncMode,
    SignalingConfig,
    SyncFilters,
    TransportConfig,
)
from ..domain.ports import ILogger, ISessionEvents


class BpyStateSync(ISessionEvents):
    """ISessionEvents implementation backed by bpy PropertyGroup.

    All bpy access is queued onto the main thread via `queue_main`.
    """

    def __init__(self, queue_main: Callable[[Callable[[], None]], None],
                 logger: ILogger) -> None:
        self._queue = queue_main
        self._logger = logger

    def on_status(self, status: str) -> None:
        self._queue(lambda: self._update(status=status))

    def on_peer_joined(self, peer) -> None:
        self._logger.info("peer joined: %s", peer.peer_id)

    def on_peer_left(self, peer_id: str) -> None:
        self._logger.info("peer left: %s", peer_id)

    def on_error(self, error: str) -> None:
        self._queue(lambda: self._update(error=error))

    def on_disconnected(self) -> None:
        self._queue(lambda: self._update(
            token="", error="", manual_answer_input="",
            latency_ms=0.0, bandwidth_kbps=0.0, peer_count=0,
        ))

    def queue_status_update(self, **kwargs) -> None:
        """Schedule a UI state mutation. Used by metrics flush, etc."""
        self._queue(lambda: self._update(**kwargs))

    def _update(self, **kwargs) -> None:
        try:
            import bpy
        except ImportError:
            return
        scene = bpy.context.scene
        if scene is None:
            return
        st = getattr(scene, "blender_sync_state", None)
        if st is None:
            return
        for key, val in kwargs.items():
            if not hasattr(st, key) or val is None:
                continue
            try:
                setattr(st, key, val)
            except Exception:
                pass


class BpyConfigReader:
    """Reads SyncFilters and ICE/relay settings from bpy.

    Pure read-only: returns Value Objects that the runtime applies. No
    direct mutation of SyncConfig from here.
    """

    def __init__(self, addon_id: str = "blender_sync") -> None:
        self._addon_id = addon_id

    def read_filters(self) -> SyncFilters | None:
        try:
            import bpy
        except ImportError:
            return None
        scene = bpy.context.scene
        if scene is None:
            return None
        st = getattr(scene, "blender_sync_state", None)
        if st is None:
            return None
        return SyncFilters(
            transform=bool(st.sync_transform),
            material=bool(st.sync_material),
            modifier=bool(st.sync_modifier),
            mesh=MeshSyncMode(
                on_edit_exit=bool(st.mesh_on_edit_exit),
                during_edit=bool(st.mesh_during_edit),
                edit_mode_hz=float(st.mesh_edit_hz),
            ),
            compositor=bool(st.sync_compositor),
            render=bool(st.sync_render),
            scene_world=bool(st.sync_scene_world),
            visibility=bool(st.sync_visibility),
            camera=bool(st.sync_camera),
            light=bool(st.sync_light),
            collection=bool(st.sync_collection),
            animation=bool(st.sync_animation),
            image=bool(st.sync_image),
            armature=bool(st.sync_armature),
            pose=bool(st.sync_pose),
            shape_keys=bool(st.sync_shape_keys),
            constraints=bool(st.sync_constraints),
            grease_pencil=bool(st.sync_grease_pencil),
            curve=bool(st.sync_curve),
            particle=bool(st.sync_particle),
            node_group=bool(st.sync_node_group),
            texture=bool(st.sync_texture),
            lattice=bool(st.sync_lattice),
            metaball=bool(st.sync_metaball),
            volume=bool(st.sync_volume),
            point_cloud=bool(st.sync_point_cloud),
            vse_strip=bool(st.sync_vse_strip),
        )

    def read_transport_config(self) -> TransportConfig | None:
        prefs = self._prefs()
        if prefs is None:
            return None
        ice = []
        if prefs.stun_url:
            ice.append(IceServer(url=prefs.stun_url))
        if prefs.turn_url:
            ice.append(IceServer(
                url=prefs.turn_url,
                username=prefs.turn_username or None,
                credential=prefs.turn_password or None,
            ))
        return TransportConfig(ice_servers=tuple(ice))

    def read_signaling_relays(self) -> tuple[str, ...] | None:
        prefs = self._prefs()
        if prefs is None or not prefs.relays:
            return None
        return tuple(r.strip() for r in prefs.relays.split(",") if r.strip())

    def read_conflict_config(self) -> ConflictResolutionConfig | None:
        try:
            import bpy
        except ImportError:
            return None
        scene = bpy.context.scene
        if scene is None:
            return None
        st = getattr(scene, "blender_sync_state", None)
        if st is None:
            return None
        priority = tuple(
            p.strip() for p in (st.conflict_peer_priority or "").split(",")
            if p.strip()
        )
        return ConflictResolutionConfig(
            policy=str(st.conflict_policy),
            window_seconds=float(st.conflict_window),
            peer_priority=priority,
        )

    def _prefs(self) -> Any:
        try:
            import bpy
        except ImportError:
            return None
        try:
            return bpy.context.preferences.addons[self._addon_id].preferences
        except Exception:
            return None

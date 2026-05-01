"""Scene + World settings handler.

Synchronizes the World data block — including its full node tree
(HDRI Environment, Sky, Volume, etc.) when use_nodes is True. Falls
back to plain `world.color` when nodes are disabled.
"""
from __future__ import annotations

from typing import Any

from . import _id_props, _nodetree


class SceneWorldCategoryHandler:
    category_name = "scene"

    def collect(self, ctx=None) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        scene = bpy.context.scene
        if scene is None:
            return []
        return [self._serialize(scene)]

    def _serialize(self, scene) -> dict[str, Any]:
        out: dict[str, Any] = {"scene": scene.name}

        # Unit settings (system / scale_length)
        us = getattr(scene, "unit_settings", None)
        if us is not None:
            unit_data: dict[str, Any] = {}
            for k in ("system", "system_rotation", "scale_length",
                      "length_unit", "mass_unit", "time_unit",
                      "temperature_unit"):
                if hasattr(us, k):
                    try:
                        v = getattr(us, k)
                        if isinstance(v, (int, float, bool, str)):
                            unit_data[k] = v
                    except Exception:
                        pass
            if unit_data:
                out["unit_settings"] = unit_data

        # Physics gravity
        try:
            out["gravity"] = list(scene.gravity)
            out["use_gravity"] = bool(scene.use_gravity)
        except Exception:
            pass

        # Audio
        if hasattr(scene, "audio_volume"):
            try:
                out["audio_volume"] = float(scene.audio_volume)
            except Exception:
                pass

        world = scene.world
        if world is None:
            return out

        wd: dict[str, Any] = {"name": world.name}
        try:
            wd["color"] = list(world.color)
        except Exception:
            pass

        # Mist settings (under world.mist_settings on classic world,
        # under scene.world.mist_settings on Cycles).
        ms = getattr(world, "mist_settings", None)
        if ms is not None:
            mist_data: dict[str, Any] = {}
            for k in ("use_mist", "intensity", "start", "depth", "height",
                      "falloff"):
                if hasattr(ms, k):
                    try:
                        v = getattr(ms, k)
                        if isinstance(v, (int, float, bool, str)):
                            mist_data[k] = v
                    except Exception:
                        pass
            if mist_data:
                wd["mist"] = mist_data
        try:
            wd["use_nodes"] = bool(world.use_nodes)
        except Exception:
            wd["use_nodes"] = False

        if world.use_nodes and world.node_tree is not None:
            wd["nodes"] = [
                _nodetree.serialize_node(n) for n in world.node_tree.nodes
            ]
            wd["links"] = [
                _nodetree.serialize_link(l) for l in world.node_tree.links
            ]

        # Custom properties on Scene and World — pipeline tools store
        # everything from asset metadata to render-farm hints here.
        scene_ip = _id_props.serialize_id_props(scene)
        if scene_ip:
            out["id_props"] = scene_ip
        world_ip = _id_props.serialize_id_props(world)
        if world_ip:
            wd["id_props"] = world_ip

        out["world"] = wd
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            scene = bpy.data.scenes.get(op.get("scene", ""))
            if scene is None:
                scene = bpy.context.scene
            if scene is None:
                continue
            self._apply_scene(bpy, scene, op)

    def _apply_scene(self, bpy, scene, op: dict[str, Any]) -> None:
        # Unit settings
        us = getattr(scene, "unit_settings", None)
        if us is not None:
            for k, v in (op.get("unit_settings") or {}).items():
                if hasattr(us, k):
                    try:
                        setattr(us, k, v)
                    except Exception:
                        pass

        gravity = op.get("gravity")
        if gravity and len(gravity) == 3:
            try:
                scene.gravity = (
                    float(gravity[0]), float(gravity[1]), float(gravity[2])
                )
            except Exception:
                pass
        if "use_gravity" in op:
            try:
                scene.use_gravity = bool(op["use_gravity"])
            except Exception:
                pass
        if "audio_volume" in op and hasattr(scene, "audio_volume"):
            try:
                scene.audio_volume = float(op["audio_volume"])
            except Exception:
                pass

        wd = op.get("world")
        if not wd:
            return
        if scene.world is None:
            try:
                scene.world = bpy.data.worlds.new(name=wd.get("name", "World"))
            except Exception:
                return
        world = scene.world
        color = wd.get("color")
        if color and hasattr(world, "color"):
            try:
                world.color = tuple(color[:3])
            except Exception:
                pass
        if "use_nodes" in wd:
            try:
                world.use_nodes = bool(wd["use_nodes"])
            except Exception:
                pass
        if world.use_nodes and world.node_tree is not None and "nodes" in wd:
            _nodetree.apply_nodetree(
                world.node_tree, wd.get("nodes", []), wd.get("links", []),
            )

        ms = getattr(world, "mist_settings", None)
        if ms is not None:
            for k, v in (wd.get("mist") or {}).items():
                if hasattr(ms, k):
                    try:
                        setattr(ms, k, v)
                    except Exception:
                        pass

        _id_props.apply_id_props(scene, op.get("id_props") or {})
        _id_props.apply_id_props(world, wd.get("id_props") or {})

    def build_full(self) -> list[dict[str, Any]]:
        return self.collect()

"""Compositor node tree handler.

Reuses the shared NodeTree serialization in `_nodetree`. Operates on
scene.node_tree (compositor) rather than material.node_tree.
"""
from __future__ import annotations

from typing import Any

from . import _nodetree


class CompositorCategoryHandler:
    category_name = "compositor"

    def collect(self, ctx=None) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        scene = bpy.context.scene
        if scene is None:
            return []
        return self._serialize(scene)

    def _serialize(self, scene) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        op: dict[str, Any] = {
            "scene": scene.name,
            "use_nodes": bool(scene.use_nodes),
        }
        if scene.use_nodes and scene.node_tree is not None:
            op["nodes"] = [_nodetree.serialize_node(n) for n in scene.node_tree.nodes]
            op["links"] = [_nodetree.serialize_link(l) for l in scene.node_tree.links]
        out.append(op)
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            scene_name = op.get("scene")
            scene = bpy.data.scenes.get(scene_name) if scene_name else bpy.context.scene
            if scene is None:
                continue
            scene.use_nodes = bool(op.get("use_nodes", False))
            if scene.use_nodes and scene.node_tree is not None and "nodes" in op:
                _nodetree.apply_nodetree(
                    scene.node_tree, op.get("nodes", []), op.get("links", [])
                )

    def build_full(self) -> list[dict[str, Any]]:
        return self.collect()

"""Compositor node tree handler.

Reuses the shared NodeTree serialization in `_nodetree`. Operates on
scene.node_tree (compositor) rather than material.node_tree.

Also covers compositor-side scene flags that the Render handler can't
reach: render-tree edit/preview shading, dither (in render), and the
node_tree's own quality / chunk settings.
"""
from __future__ import annotations

from typing import Any

from . import _nodetree


# Settings that live on the compositor's node_tree itself (not on
# scene). Present in Blender 4.x; gated via hasattr for forward-compat.
_TREE_FIELDS = (
    "edit_quality",
    "render_quality",
    "chunk_size",
    "use_opencl",
    "use_groupnode_buffer",
    "use_two_pass",
    "use_viewer_border",
)


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
            tree = scene.node_tree
            op["nodes"] = [_nodetree.serialize_node(n) for n in tree.nodes]
            op["links"] = [_nodetree.serialize_link(l) for l in tree.links]
            tree_props: dict[str, Any] = {}
            for f in _TREE_FIELDS:
                if not hasattr(tree, f):
                    continue
                try:
                    v = getattr(tree, f)
                except Exception:
                    continue
                if isinstance(v, (int, float, bool, str)):
                    tree_props[f] = v
            if tree_props:
                op["tree_props"] = tree_props
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
                tree = scene.node_tree
                for k, v in (op.get("tree_props") or {}).items():
                    if not hasattr(tree, k):
                        continue
                    try:
                        cur = getattr(tree, k)
                        if isinstance(cur, bool):
                            setattr(tree, k, bool(v))
                        elif isinstance(cur, (int, float)):
                            setattr(tree, k, type(cur)(v))
                        else:
                            setattr(tree, k, v)
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        return self.collect()

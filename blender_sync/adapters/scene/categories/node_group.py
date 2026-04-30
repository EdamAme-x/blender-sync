"""NodeGroup data block handler.

`bpy.data.node_groups` holds shared NodeTree datablocks that live
independently from any owning material/world/scene. Without syncing
them, a peer that creates a Geometry Nodes / Shader Group cannot
reproduce the inner network — references resolve by name but the
referenced tree is empty.
"""
from __future__ import annotations

from typing import Any

from . import _nodetree
from .base import DirtyContext


class NodeGroupCategoryHandler:
    category_name = "node_group"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.node_groups):
            ng = bpy.data.node_groups.get(name)
            if ng is None:
                continue
            ops.append(self._serialize(ng))
        return ops

    def _serialize(self, ng) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": ng.name,
            "bl_idname": ng.bl_idname,
            "nodes": [_nodetree.serialize_node(n) for n in ng.nodes],
            "links": [_nodetree.serialize_link(l) for l in ng.links],
        }
        iface = _nodetree.serialize_tree_interface(ng)
        if iface:
            out["interface"] = iface
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            name = op.get("name", "")
            if not name:
                continue
            ng = bpy.data.node_groups.get(name)
            if ng is None:
                try:
                    ng = bpy.data.node_groups.new(
                        name=name, type=op.get("bl_idname", "ShaderNodeTree"),
                    )
                except Exception:
                    continue
            iface = op.get("interface")
            if iface:
                _nodetree.apply_tree_interface(ng, iface)
            _nodetree.apply_nodetree(
                ng, op.get("nodes") or [], op.get("links") or [],
            )

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(g) for g in bpy.data.node_groups]

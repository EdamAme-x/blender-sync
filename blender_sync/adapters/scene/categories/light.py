"""Light datablock handler.

Synchronizes light-specific properties (type, energy, color, soft size,
spot angle, ...) for any bpy.types.Light datablock.
"""
from __future__ import annotations

from typing import Any

from . import _nodetree
from .base import DirtyContext


_LIGHT_FIELDS_COMMON = [
    "type", "color", "energy", "specular_factor",
    "diffuse_factor", "volume_factor", "use_shadow",
]

_LIGHT_FIELDS_POINT = ["shadow_soft_size"]
_LIGHT_FIELDS_SPOT = ["spot_size", "spot_blend", "show_cone"]
_LIGHT_FIELDS_SUN = ["angle"]
_LIGHT_FIELDS_AREA = ["shape", "size", "size_y"]


def _collect_fields(light, fields: list[str], out: dict[str, Any]) -> None:
    for f in fields:
        if not hasattr(light, f):
            continue
        try:
            val = getattr(light, f)
            if isinstance(val, (int, float, bool, str)):
                out[f] = val
            elif hasattr(val, "__len__"):
                try:
                    out[f] = [float(c) for c in val]
                except Exception:
                    pass
        except Exception:
            pass


class LightCategoryHandler:
    category_name = "light"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.lights):
            light = bpy.data.lights.get(name)
            if light is None:
                continue
            ops.append(self._serialize(light))
        return ops

    def _serialize(self, light) -> dict[str, Any]:
        props: dict[str, Any] = {}
        _collect_fields(light, _LIGHT_FIELDS_COMMON, props)
        ltype = getattr(light, "type", "")
        if ltype == "POINT":
            _collect_fields(light, _LIGHT_FIELDS_POINT, props)
        elif ltype == "SPOT":
            _collect_fields(light, _LIGHT_FIELDS_SPOT + _LIGHT_FIELDS_POINT, props)
        elif ltype == "SUN":
            _collect_fields(light, _LIGHT_FIELDS_SUN, props)
        elif ltype == "AREA":
            _collect_fields(light, _LIGHT_FIELDS_AREA, props)
        out: dict[str, Any] = {"name": light.name, "props": props}
        if getattr(light, "use_nodes", False) and getattr(light, "node_tree", None):
            out["use_nodes"] = True
            out["nodes"] = [
                _nodetree.serialize_node(n) for n in light.node_tree.nodes
            ]
            out["links"] = [
                _nodetree.serialize_link(l) for l in light.node_tree.links
            ]
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            light = bpy.data.lights.get(op.get("name", ""))
            if light is None:
                continue
            for k, v in (op.get("props") or {}).items():
                if not hasattr(light, k):
                    continue
                try:
                    cur = getattr(light, k)
                    if isinstance(v, list) and hasattr(cur, "__len__"):
                        setattr(light, k, tuple(v))
                    else:
                        setattr(light, k, v)
                except Exception:
                    pass
            if op.get("use_nodes") and "nodes" in op:
                try:
                    light.use_nodes = True
                    if light.node_tree is not None:
                        _nodetree.apply_nodetree(
                            light.node_tree,
                            op.get("nodes") or [],
                            op.get("links") or [],
                        )
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(l) for l in bpy.data.lights]

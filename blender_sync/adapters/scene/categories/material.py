"""Material category handler.

Serializes the entire node tree of a Material:
  - all nodes (type, name, location, properties, default input values)
  - all links between sockets

The serialization is lossy by necessity (Blender exposes hundreds of node
types with arbitrary parameters), but covers the common BSDF / Texture /
Math / Mix / RGB / ColorRamp nodes accurately.
"""
from __future__ import annotations

from typing import Any

from . import _id_props, _nodetree


class MaterialCategoryHandler:
    category_name = "material"

    def collect_dirty(self, dirty_material_names: set) -> list[dict[str, Any]]:
        return self._collect(dirty_material_names)

    def collect(self, ctx) -> list[dict[str, Any]]:
        return self._collect(ctx.materials)

    def _collect(self, names) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(names):
            mat = bpy.data.materials.get(name)
            if mat is None:
                continue
            ops.append(self._serialize_material(mat))
        return ops

    def _serialize_material(self, mat) -> dict[str, Any]:
        op: dict[str, Any] = {
            "mat": mat.name,
            "use_nodes": bool(mat.use_nodes),
            "diffuse_color": list(mat.diffuse_color),
            "metallic": float(getattr(mat, "metallic", 0.0)),
            "roughness": float(getattr(mat, "roughness", 0.5)),
            "use_backface_culling": bool(getattr(mat, "use_backface_culling", False)),
        }
        # Blend method moved/renamed in Blender 5 EEVEE Next; keep both forms.
        for k in ("blend_method", "surface_render_method", "shadow_method"):
            if hasattr(mat, k):
                try:
                    val = getattr(mat, k)
                    if isinstance(val, (int, float, bool, str)):
                        op[k] = val
                except Exception:
                    pass
        if mat.use_nodes and mat.node_tree is not None:
            op["nodes"] = [_nodetree.serialize_node(n) for n in mat.node_tree.nodes]
            op["links"] = [_nodetree.serialize_link(l) for l in mat.node_tree.links]
            iface = _nodetree.serialize_tree_interface(mat.node_tree)
            if iface:
                op["interface"] = iface
        ip = _id_props.serialize_id_props(mat)
        if ip:
            op["id_props"] = ip
        return op

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            self._apply_material(bpy, op)

    def _apply_material(self, bpy, op: dict[str, Any]) -> None:
        mat_name = op.get("mat")
        if not mat_name:
            return
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)

        mat.use_nodes = bool(op.get("use_nodes", True))
        diffuse = op.get("diffuse_color")
        if diffuse and len(diffuse) >= 3:
            try:
                mat.diffuse_color = tuple(float(c) for c in diffuse[:4])
            except Exception:
                pass
        for k in ("metallic", "roughness"):
            if k in op and hasattr(mat, k):
                try:
                    setattr(mat, k, float(op[k]))
                except Exception:
                    pass
        if "use_backface_culling" in op and hasattr(mat, "use_backface_culling"):
            try:
                mat.use_backface_culling = bool(op["use_backface_culling"])
            except Exception:
                pass
        for k in ("blend_method", "surface_render_method", "shadow_method"):
            if k in op and hasattr(mat, k):
                try:
                    setattr(mat, k, op[k])
                except Exception:
                    pass

        if mat.use_nodes and mat.node_tree is not None and "nodes" in op:
            _nodetree.apply_nodetree(
                mat.node_tree, op.get("nodes", []), op.get("links", [])
            )
            iface = op.get("interface")
            if iface:
                _nodetree.apply_tree_interface(mat.node_tree, iface)
        _id_props.apply_id_props(mat, op.get("id_props") or {})

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize_material(m) for m in bpy.data.materials]

"""Mesh handler. Two modes:

- on_edit_exit: when an object transitions EDIT -> OBJECT, send a full snapshot
  of vertices/edges/faces/uv/normals.
- during_edit: optional 5-10Hz sampling of the active edit-mode mesh
  (vertex coordinates only, hashed to skip identical sends).

Both produce the same 'mesh' op shape; the receiver applies via bmesh.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


def _mesh_hash(verts: list, faces: list) -> str:
    h = hashlib.blake2b(digest_size=8)
    for v in verts:
        h.update(struct.pack("<fff", float(v[0]), float(v[1]), float(v[2])))
    for f in faces:
        h.update(struct.pack(f"<{len(f)}I", *(int(i) for i in f)))
    return h.hexdigest()


def _hash_buffers(vert_buf: bytes, face_buf: bytes) -> str:
    h = hashlib.blake2b(digest_size=8)
    h.update(vert_buf)
    h.update(face_buf)
    return h.hexdigest()


class MeshCategoryHandler:
    category_name = "mesh"

    def __init__(self) -> None:
        self._sent_hash: dict[str, str] = {}

    def collect_dirty(
        self,
        committed_objs: set,
        editing_objs: set,
    ) -> list[dict[str, Any]]:
        return self._collect(committed_objs, editing_objs)

    def collect(self, ctx) -> list[dict[str, Any]]:
        return self._collect(ctx.meshes_committed, ctx.meshes_editing)

    def _collect(self, committed_objs, editing_objs) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []

        ops: list[dict[str, Any]] = []
        for name in list(committed_objs):
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                continue
            op = self._serialize(obj, full=True)
            if op is not None and self._mark_if_changed(name, op["hash"]):
                ops.append(op)

        for name in list(editing_objs):
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                continue
            op = self._serialize(obj, full=False)
            if op is not None and self._mark_if_changed(name, op["hash"]):
                ops.append(op)
        return ops

    def _mark_if_changed(self, name: str, h: str) -> bool:
        if self._sent_hash.get(name) == h:
            return False
        self._sent_hash[name] = h
        return True

    def _serialize(self, obj, *, full: bool) -> dict[str, Any] | None:
        mesh = obj.data
        if mesh is None:
            return None

        if obj.mode == "EDIT":
            try:
                obj.update_from_editmode()
            except Exception:
                return None

        self._last_mat_idx = None
        self._last_extras = {}
        if _HAS_NUMPY:
            verts, faces, hash_hex, edges_np, uvs_np = self._extract_numpy(mesh, full)
            mat_idx = self._last_mat_idx or []
            extras = self._last_extras
        else:
            verts = [list(v.co) for v in mesh.vertices]
            faces = [list(p.vertices) for p in mesh.polygons]
            hash_hex = _mesh_hash(verts, faces)
            edges_np = None
            uvs_np = None
            mat_idx = [int(p.material_index) for p in mesh.polygons]
            extras = {}

        op: dict[str, Any] = {
            "obj": obj.name,
            "mesh": mesh.name,
            "verts": verts,
            "faces": faces,
            "hash": hash_hex,
            "mat_idx": mat_idx,
        }

        if full:
            if edges_np is not None:
                op["edges"] = edges_np
            else:
                op["edges"] = [list(e.vertices) for e in mesh.edges]

            if uvs_np is not None:
                op["uvs"] = uvs_np
            elif mesh.uv_layers.active is not None:
                uvs = []
                for loop in mesh.uv_layers.active.data:
                    uvs.append([float(loop.uv[0]), float(loop.uv[1])])
                op["uvs"] = uvs

            try:
                op["normals_auto"] = bool(getattr(mesh, "use_auto_smooth", False))
            except Exception:
                pass

            # Vertex group definitions live on the Object, not the Mesh.
            try:
                vg_names = [vg.name for vg in obj.vertex_groups]
                if vg_names:
                    op["vertex_groups"] = vg_names
            except Exception:
                pass

            # Numpy-extracted bonus payload (multi-UV, vcol, weights, flags).
            if extras:
                op["extras"] = extras
        return op

    def _extract_numpy(self, mesh, full: bool):
        n_verts = len(mesh.vertices)
        n_polys = len(mesh.polygons)

        co = _np.empty(n_verts * 3, dtype=_np.float32)
        mesh.vertices.foreach_get("co", co)

        loop_totals = _np.empty(n_polys, dtype=_np.int32)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        loop_starts = _np.empty(n_polys, dtype=_np.int32)
        mesh.polygons.foreach_get("loop_start", loop_starts)

        n_loops = len(mesh.loops)
        loop_verts = _np.empty(n_loops, dtype=_np.int32)
        mesh.loops.foreach_get("vertex_index", loop_verts)

        faces: list[list[int]] = []
        for i in range(n_polys):
            s = int(loop_starts[i]); t = int(loop_totals[i])
            faces.append(loop_verts[s:s + t].tolist())

        verts = co.reshape(-1, 3).tolist()

        hash_hex = _hash_buffers(co.tobytes(), loop_verts.tobytes())

        edges_out = None
        uvs_out = None
        extras: dict[str, Any] = {}
        if full:
            n_edges = len(mesh.edges)
            edge_buf = _np.empty(n_edges * 2, dtype=_np.int32)
            mesh.edges.foreach_get("vertices", edge_buf)
            edges_out = edge_buf.reshape(-1, 2).tolist()

            # Active UV (legacy single-layer field, kept for compat).
            if mesh.uv_layers.active is not None:
                uv_buf = _np.empty(n_loops * 2, dtype=_np.float32)
                mesh.uv_layers.active.data.foreach_get("uv", uv_buf)
                uvs_out = uv_buf.reshape(-1, 2).tolist()

            # All UV layers (multi-UV support).
            uv_layers = []
            for layer in mesh.uv_layers:
                buf = _np.empty(n_loops * 2, dtype=_np.float32)
                layer.data.foreach_get("uv", buf)
                uv_layers.append({
                    "name": layer.name,
                    "active_render": bool(getattr(layer, "active_render", False)),
                    "uvs": buf.reshape(-1, 2).tolist(),
                })
            if uv_layers:
                extras["uv_layers"] = uv_layers

            # Color attributes (point/loop domain).
            color_attrs = []
            attrs_iter = getattr(mesh, "color_attributes", None)
            if attrs_iter is not None:
                for ca in attrs_iter:
                    n = len(ca.data)
                    if n == 0:
                        continue
                    buf = _np.empty(n * 4, dtype=_np.float32)
                    try:
                        ca.data.foreach_get("color", buf)
                    except Exception:
                        continue
                    color_attrs.append({
                        "name": ca.name,
                        "domain": ca.domain,
                        "data_type": ca.data_type,
                        "colors": buf.reshape(-1, 4).tolist(),
                    })
            if color_attrs:
                extras["color_attrs"] = color_attrs

            # Vertex groups (deform weights).
            vg_buffer: list[dict[str, Any]] = []
            for v_idx, v in enumerate(mesh.vertices):
                groups = getattr(v, "groups", None)
                if not groups:
                    continue
                gs = [(int(g.group), float(g.weight)) for g in groups]
                if gs:
                    vg_buffer.append({"i": v_idx, "g": gs})
            if vg_buffer:
                extras["vertex_groups_data"] = vg_buffer

            # Per-polygon flags
            smooth_buf = _np.empty(n_polys, dtype=_np.bool_)
            mesh.polygons.foreach_get("use_smooth", smooth_buf)
            extras["face_smooth"] = smooth_buf.tolist()

            # Edge flags + crease/bevel weight
            n_edges = len(mesh.edges)
            if n_edges > 0:
                eflags = {}
                for f in ("use_edge_sharp", "use_seam"):
                    buf = _np.empty(n_edges, dtype=_np.bool_)
                    try:
                        mesh.edges.foreach_get(f, buf)
                        eflags[f] = buf.tolist()
                    except Exception:
                        pass
                if eflags:
                    extras["edge_flags"] = eflags

                eweights = {}
                for f in ("crease", "bevel_weight"):
                    buf = _np.empty(n_edges, dtype=_np.float32)
                    try:
                        mesh.edges.foreach_get(f, buf)
                        eweights[f] = buf.tolist()
                    except Exception:
                        pass
                if eweights:
                    extras["edge_weights"] = eweights

            # Per-vertex bevel weight
            if n_verts > 0:
                vbuf = _np.empty(n_verts, dtype=_np.float32)
                try:
                    mesh.vertices.foreach_get("bevel_weight", vbuf)
                    extras["vertex_bevel_weight"] = vbuf.tolist()
                except Exception:
                    pass

            # Custom split normals (loop normals). Only present when
            # use_auto_smooth or custom normals were stored.
            if getattr(mesh, "use_auto_smooth", False) and n_loops > 0:
                try:
                    mesh.calc_normals_split()
                    nbuf = _np.empty(n_loops * 3, dtype=_np.float32)
                    mesh.loops.foreach_get("normal", nbuf)
                    extras["loop_normals"] = nbuf.reshape(-1, 3).tolist()
                except Exception:
                    pass

        # Per-polygon material_index — extracted regardless of `full` since
        # missing it produces all faces on slot 0 on the receiver.
        if n_polys > 0:
            mat_idx_buf = _np.empty(n_polys, dtype=_np.int32)
            mesh.polygons.foreach_get("material_index", mat_idx_buf)
            self._last_mat_idx = mat_idx_buf.tolist()
        else:
            self._last_mat_idx = []

        self._last_extras = extras
        return verts, faces, hash_hex, edges_out, uvs_out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            self._apply_one(bpy, op)

    def _apply_one(self, bpy, op: dict[str, Any]) -> None:
        obj_name = op.get("obj")
        if not obj_name:
            return

        mesh_name = op.get("mesh", obj_name)
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            mesh = bpy.data.meshes.new(mesh_name)
            obj = bpy.data.objects.new(obj_name, mesh)
            try:
                bpy.context.scene.collection.objects.link(obj)
            except Exception:
                pass
        if obj.type != "MESH" or obj.data is None:
            return

        mesh = obj.data
        verts = op.get("verts") or []
        faces = op.get("faces") or []
        edges = op.get("edges") or []

        try:
            mesh.clear_geometry()
            mesh.from_pydata(
                [tuple(v) for v in verts],
                [tuple(e) for e in edges],
                [tuple(f) for f in faces],
            )
            mesh.update(calc_edges=True)
        except Exception:
            return

        uvs = op.get("uvs")
        if uvs:
            try:
                if not mesh.uv_layers:
                    mesh.uv_layers.new(name="UVMap")
                layer = mesh.uv_layers.active
                if layer is not None:
                    for i, loop in enumerate(layer.data):
                        if i < len(uvs):
                            loop.uv = (float(uvs[i][0]), float(uvs[i][1]))
            except Exception:
                pass

        mat_idx = op.get("mat_idx")
        if mat_idx:
            try:
                for i, poly in enumerate(mesh.polygons):
                    if i < len(mat_idx):
                        poly.material_index = int(mat_idx[i])
            except Exception:
                pass

        # Vertex group definitions on the Object.
        vg_names = op.get("vertex_groups")
        if vg_names:
            try:
                existing = {vg.name for vg in obj.vertex_groups}
                for name in vg_names:
                    if name not in existing:
                        obj.vertex_groups.new(name=name)
            except Exception:
                pass

        extras = op.get("extras") or {}
        self._apply_extras(mesh, obj, extras)

        h = op.get("hash")
        if h:
            self._sent_hash[obj_name] = h

    def _apply_extras(self, mesh, obj, extras: dict) -> None:
        # Multi-UV layers
        uv_layers = extras.get("uv_layers") or []
        if uv_layers:
            try:
                while len(mesh.uv_layers) > 0:
                    mesh.uv_layers.remove(mesh.uv_layers[0])
                for layer_data in uv_layers:
                    layer = mesh.uv_layers.new(
                        name=layer_data.get("name", "UVMap")
                    )
                    if layer_data.get("active_render"):
                        try:
                            layer.active_render = True
                        except Exception:
                            pass
                    coords = layer_data.get("uvs") or []
                    for i, loop in enumerate(layer.data):
                        if i < len(coords):
                            loop.uv = (float(coords[i][0]), float(coords[i][1]))
            except Exception:
                pass

        # Color attributes
        color_attrs = extras.get("color_attrs") or []
        if color_attrs and hasattr(mesh, "color_attributes"):
            try:
                while len(mesh.color_attributes) > 0:
                    mesh.color_attributes.remove(mesh.color_attributes[0])
                for ca_data in color_attrs:
                    ca = mesh.color_attributes.new(
                        name=ca_data.get("name", "Col"),
                        type=ca_data.get("data_type", "FLOAT_COLOR"),
                        domain=ca_data.get("domain", "POINT"),
                    )
                    colors = ca_data.get("colors") or []
                    for i, item in enumerate(ca.data):
                        if i < len(colors):
                            c = colors[i]
                            if len(c) >= 4:
                                item.color = (
                                    float(c[0]), float(c[1]),
                                    float(c[2]), float(c[3]),
                                )
            except Exception:
                pass

        # Per-vertex weights (vertex group assignments)
        vg_data = extras.get("vertex_groups_data") or []
        if vg_data:
            try:
                for entry in vg_data:
                    v_idx = int(entry.get("i", -1))
                    if v_idx < 0 or v_idx >= len(mesh.vertices):
                        continue
                    for g_idx, weight in entry.get("g", []):
                        g_idx = int(g_idx)
                        if g_idx >= len(obj.vertex_groups):
                            continue
                        try:
                            obj.vertex_groups[g_idx].add(
                                [v_idx], float(weight), "REPLACE"
                            )
                        except Exception:
                            pass
            except Exception:
                pass

        # Per-polygon flags
        face_smooth = extras.get("face_smooth")
        if face_smooth:
            try:
                for i, poly in enumerate(mesh.polygons):
                    if i < len(face_smooth):
                        poly.use_smooth = bool(face_smooth[i])
            except Exception:
                pass

        # Edge flags
        eflags = extras.get("edge_flags") or {}
        for fname, vals in eflags.items():
            try:
                for i, e in enumerate(mesh.edges):
                    if i < len(vals):
                        setattr(e, fname, bool(vals[i]))
            except Exception:
                pass

        eweights = extras.get("edge_weights") or {}
        for fname, vals in eweights.items():
            try:
                for i, e in enumerate(mesh.edges):
                    if i < len(vals):
                        setattr(e, fname, float(vals[i]))
            except Exception:
                pass

        vbevel = extras.get("vertex_bevel_weight")
        if vbevel:
            try:
                for i, v in enumerate(mesh.vertices):
                    if i < len(vbevel):
                        v.bevel_weight = float(vbevel[i])
            except Exception:
                pass

        loop_normals = extras.get("loop_normals")
        if loop_normals:
            try:
                if not getattr(mesh, "use_auto_smooth", False):
                    mesh.use_auto_smooth = True
                mesh.normals_split_custom_set(
                    [tuple(n) for n in loop_normals]
                )
            except Exception:
                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            op = self._serialize(obj, full=True)
            if op is not None:
                ops.append(op)
                self._sent_hash[obj.name] = op["hash"]
        return ops

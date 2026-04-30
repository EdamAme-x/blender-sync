"""Grease Pencil data block handler.

Synchronizes 2D animation strokes:
  - layers (name, opacity, hide, lock, blend_mode)
  - frames per layer (frame_number)
  - strokes per frame (line_width, material_index, points)
  - points (co, pressure, strength)

Strokes can be very large for complex 2D scenes; we send full data when
a Grease Pencil data block is dirty (no per-stroke diff yet).
"""
from __future__ import annotations

import hashlib
from typing import Any

from .base import DirtyContext

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


def _gp_collection(bpy):
    """Return the Grease Pencil data block collection for this Blender
    version. v3 (Blender 4.3+) uses `grease_pencils_v3`; older versions
    use `grease_pencils`. Returns None if neither exists."""
    return (
        getattr(bpy.data, "grease_pencils_v3", None)
        or getattr(bpy.data, "grease_pencils", None)
    )


def _serialize_point(p) -> list[float]:
    return [
        float(p.co[0]), float(p.co[1]), float(p.co[2]),
        float(getattr(p, "pressure", 1.0)),
        float(getattr(p, "strength", 1.0)),
    ]


def _serialize_stroke(stroke) -> dict[str, Any]:
    return {
        "line_width": int(getattr(stroke, "line_width", 12)),
        "material_index": int(getattr(stroke, "material_index", 0)),
        "draw_cyclic": bool(getattr(stroke, "draw_cyclic",
                                    getattr(stroke, "use_cyclic", False))),
        "points": [_serialize_point(p) for p in stroke.points],
    }


def _serialize_frame(frame) -> dict[str, Any]:
    return {
        "frame_number": int(frame.frame_number),
        "strokes": [_serialize_stroke(s) for s in frame.strokes],
    }


def _layer_name(layer) -> str:
    """Read the layer name across both GP v2 (.info) and v3 (.name) APIs."""
    name = getattr(layer, "name", None)
    if isinstance(name, str) and name:
        return name
    info = getattr(layer, "info", None)
    if isinstance(info, str):
        return info
    return ""


def _layer_frames(layer):
    """Iterate frames across GP v2 (`layer.frames`) and v3 schemas where
    frames may be exposed via `layer.frames` or via `layer.layers[0].frames`
    depending on the Blender version. Returns an iterable, possibly empty."""
    frames = getattr(layer, "frames", None)
    if frames is not None:
        return frames
    return ()


def _serialize_layer(layer) -> dict[str, Any]:
    return {
        "name": _layer_name(layer),
        "opacity": float(getattr(layer, "opacity", 1.0)),
        "hide": bool(getattr(layer, "hide", False)),
        "lock": bool(getattr(layer, "lock", False)),
        "blend_mode": getattr(layer, "blend_mode", "REGULAR"),
        "frames": [_serialize_frame(f) for f in _layer_frames(layer)],
    }


class GreasePencilCategoryHandler:
    category_name = "grease_pencil"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        gp_collection = _gp_collection(bpy)
        if gp_collection is None:
            return []
        for name in list(ctx.grease_pencils):
            gp = gp_collection.get(name)
            if gp is None:
                continue
            ops.append(self._serialize(gp))
        return ops

    def _serialize(self, gp) -> dict[str, Any]:
        return {
            "name": gp.name,
            "layers": [_serialize_layer(l) for l in gp.layers],
        }

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        gp_collection = _gp_collection(bpy)
        if gp_collection is None:
            return
        for op in ops:
            name = op.get("name", "")
            gp = gp_collection.get(name)
            if gp is None:
                try:
                    gp = gp_collection.new(name)
                except Exception:
                    continue
            self._apply_layers(gp, op.get("layers") or [])

    def _apply_layers(self, gp, layers_data: list) -> None:
        target_names = {l["name"] for l in layers_data}
        try:
            for l in list(gp.layers):
                if _layer_name(l) not in target_names:
                    gp.layers.remove(l)
        except Exception:
            pass
        for ld in layers_data:
            layer = None
            try:
                layer = gp.layers.get(ld["name"])
            except Exception:
                pass
            if layer is None:
                # v2: gp.layers.new(name=...). v3: same kwarg.
                try:
                    layer = gp.layers.new(name=ld["name"])
                except Exception:
                    continue
            for k in ("opacity",):
                if k in ld:
                    try:
                        setattr(layer, k, float(ld[k]))
                    except Exception:
                        pass
            for k in ("hide", "lock"):
                if k in ld:
                    try:
                        setattr(layer, k, bool(ld[k]))
                    except Exception:
                        pass
            if "blend_mode" in ld:
                try:
                    layer.blend_mode = ld["blend_mode"]
                except Exception:
                    pass
            self._apply_frames(layer, ld.get("frames") or [])

    def _apply_frames(self, layer, frames_data: list) -> None:
        try:
            for f in list(layer.frames):
                layer.frames.remove(f)
        except Exception:
            pass
        for fd in frames_data:
            try:
                frame = layer.frames.new(int(fd.get("frame_number", 1)))
            except Exception:
                continue
            for sd in fd.get("strokes") or []:
                try:
                    stroke = frame.strokes.new()
                    if "line_width" in sd:
                        stroke.line_width = int(sd["line_width"])
                    if "material_index" in sd:
                        stroke.material_index = int(sd["material_index"])
                    points = sd.get("points") or []
                    stroke.points.add(len(points))
                    for i, p_data in enumerate(points):
                        if i >= len(stroke.points) or len(p_data) < 3:
                            continue
                        pt = stroke.points[i]
                        pt.co = (
                            float(p_data[0]), float(p_data[1]), float(p_data[2])
                        )
                        if len(p_data) > 3:
                            try:
                                pt.pressure = float(p_data[3])
                            except Exception:
                                pass
                        if len(p_data) > 4:
                            try:
                                pt.strength = float(p_data[4])
                            except Exception:
                                pass
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        gp_collection = _gp_collection(bpy)
        if gp_collection is None:
            return []
        return [self._serialize(g) for g in gp_collection]

"""Curve / NURBS / Text object data handler.

Synchronizes the bpy.types.Curve datablock for objects of type CURVE,
SURFACE, FONT (text). Common payload covers:
  - splines list (bezier / nurbs / poly)
  - per-spline points (co, handle_left, handle_right, tilt, weight)
  - bevel/extrude depth, resolution_u/v, fill_mode
  - Text-only fields: body, size, extrude, font reference (by name)
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
from .base import DirtyContext


_COMMON_FIELDS = [
    "dimensions", "resolution_u", "resolution_v",
    "render_resolution_u", "render_resolution_v",
    "fill_mode",
    "bevel_depth", "bevel_resolution",
    "extrude", "offset",
    "use_path", "use_path_follow", "use_radius",
    "use_stretch", "use_deform_bounds",
    "twist_mode", "twist_smooth",
    "path_duration",
]


def _serialize_bezier_point(p) -> dict[str, Any]:
    return {
        "co": list(p.co),
        "left": list(p.handle_left),
        "right": list(p.handle_right),
        "left_type": getattr(p, "handle_left_type", "FREE"),
        "right_type": getattr(p, "handle_right_type", "FREE"),
        "tilt": float(getattr(p, "tilt", 0.0)),
        "radius": float(getattr(p, "radius", 1.0)),
    }


def _serialize_nurbs_point(p) -> dict[str, Any]:
    return {
        "co": list(p.co),
        "weight": float(getattr(p, "weight", 1.0)),
        "tilt": float(getattr(p, "tilt", 0.0)),
        "radius": float(getattr(p, "radius", 1.0)),
    }


def _serialize_spline(s) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": s.type,
        "use_cyclic_u": bool(getattr(s, "use_cyclic_u", False)),
        "use_cyclic_v": bool(getattr(s, "use_cyclic_v", False)),
        "resolution_u": int(getattr(s, "resolution_u", 12)),
        "resolution_v": int(getattr(s, "resolution_v", 12)),
        "order_u": int(getattr(s, "order_u", 4)),
        "order_v": int(getattr(s, "order_v", 4)),
    }
    if s.type == "BEZIER":
        out["bezier_points"] = [_serialize_bezier_point(p) for p in s.bezier_points]
    else:
        out["points"] = [_serialize_nurbs_point(p) for p in s.points]
    return out


class CurveCategoryHandler:
    category_name = "curve"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.curves):
            curve = bpy.data.curves.get(name)
            if curve is None:
                continue
            ops.append(self._serialize(curve))
        return ops

    def _serialize(self, curve) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": curve.name,
            "dim": getattr(curve, "dimensions", "3D"),
            "splines": [_serialize_spline(s) for s in curve.splines],
            "props": {},
        }
        for f in _COMMON_FIELDS:
            if hasattr(curve, f):
                try:
                    val = getattr(curve, f)
                    if isinstance(val, (int, float, bool, str)):
                        out["props"][f] = val
                except Exception:
                    pass

        # Text-specific fields (TextCurve subclass)
        if hasattr(curve, "body"):
            out["text"] = {
                "body": str(getattr(curve, "body", "")),
                "size": float(getattr(curve, "size", 1.0)),
                "shear": float(getattr(curve, "shear", 0.0)),
                "space_character": float(getattr(curve, "space_character", 1.0)),
                "space_word": float(getattr(curve, "space_word", 1.0)),
                "align_x": getattr(curve, "align_x", "LEFT"),
                "align_y": getattr(curve, "align_y", "TOP"),
            }
            font = getattr(curve, "font", None)
            if font is not None:
                ref = _datablock_ref.try_ref(font)
                if ref:
                    out["text"]["font"] = ref

        # Bevel / taper object references
        bvl = getattr(curve, "bevel_object", None)
        if bvl is not None:
            ref = _datablock_ref.try_ref(bvl)
            if ref:
                out["bevel_object"] = ref
        tpr = getattr(curve, "taper_object", None)
        if tpr is not None:
            ref = _datablock_ref.try_ref(tpr)
            if ref:
                out["taper_object"] = ref
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            curve = bpy.data.curves.get(op.get("name", ""))
            if curve is None:
                continue
            try:
                curve.dimensions = op.get("dim", "3D")
            except Exception:
                pass
            for k, v in (op.get("props") or {}).items():
                if hasattr(curve, k):
                    try:
                        setattr(curve, k, v)
                    except Exception:
                        pass

            text_data = op.get("text") or {}
            if text_data and hasattr(curve, "body"):
                for k in ("body",):
                    if k in text_data:
                        try:
                            setattr(curve, k, str(text_data[k]))
                        except Exception:
                            pass
                for k in ("size", "shear", "space_character", "space_word"):
                    if k in text_data and hasattr(curve, k):
                        try:
                            setattr(curve, k, float(text_data[k]))
                        except Exception:
                            pass
                for k in ("align_x", "align_y"):
                    if k in text_data and hasattr(curve, k):
                        try:
                            setattr(curve, k, text_data[k])
                        except Exception:
                            pass

            for k in ("bevel_object", "taper_object"):
                if k in op:
                    resolved = _datablock_ref.resolve_ref(op[k])
                    if resolved is not None:
                        try:
                            setattr(curve, k, resolved)
                        except Exception:
                            pass

            self._apply_splines(curve, op.get("splines") or [])

    def _apply_splines(self, curve, splines_data: list) -> None:
        try:
            curve.splines.clear()
        except Exception:
            return
        for sd in splines_data:
            try:
                s = curve.splines.new(type=sd.get("type", "POLY"))
            except Exception:
                continue
            for k in ("use_cyclic_u", "use_cyclic_v"):
                if k in sd and hasattr(s, k):
                    try:
                        setattr(s, k, bool(sd[k]))
                    except Exception:
                        pass
            for k in ("resolution_u", "resolution_v", "order_u", "order_v"):
                if k in sd and hasattr(s, k):
                    try:
                        setattr(s, k, int(sd[k]))
                    except Exception:
                        pass

            if sd.get("type") == "BEZIER":
                pts = sd.get("bezier_points") or []
                # Bezier splines start with 1 point; add the rest.
                if len(pts) > 1:
                    s.bezier_points.add(len(pts) - 1)
                for i, pd in enumerate(pts):
                    if i >= len(s.bezier_points):
                        break
                    bp = s.bezier_points[i]
                    co = pd.get("co") or [0, 0, 0]
                    if len(co) >= 3:
                        bp.co = (float(co[0]), float(co[1]), float(co[2]))
                    left = pd.get("left") or co
                    right = pd.get("right") or co
                    if len(left) >= 3:
                        bp.handle_left = (float(left[0]), float(left[1]), float(left[2]))
                    if len(right) >= 3:
                        bp.handle_right = (float(right[0]), float(right[1]), float(right[2]))
                    for k_src, k_dst in (
                        ("left_type", "handle_left_type"),
                        ("right_type", "handle_right_type"),
                    ):
                        if k_src in pd:
                            try:
                                setattr(bp, k_dst, pd[k_src])
                            except Exception:
                                pass
                    for k in ("tilt", "radius"):
                        if k in pd:
                            try:
                                setattr(bp, k, float(pd[k]))
                            except Exception:
                                pass
            else:
                pts = sd.get("points") or []
                if len(pts) > 1:
                    s.points.add(len(pts) - 1)
                for i, pd in enumerate(pts):
                    if i >= len(s.points):
                        break
                    sp = s.points[i]
                    co = pd.get("co") or [0, 0, 0, 1]
                    if len(co) >= 4:
                        sp.co = (
                            float(co[0]), float(co[1]),
                            float(co[2]), float(co[3]),
                        )
                    elif len(co) == 3:
                        sp.co = (float(co[0]), float(co[1]), float(co[2]), 1.0)
                    for k in ("weight", "tilt", "radius"):
                        if k in pd:
                            try:
                                setattr(sp, k, float(pd[k]))
                            except Exception:
                                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(c) for c in bpy.data.curves]

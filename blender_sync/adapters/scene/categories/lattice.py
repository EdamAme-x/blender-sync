"""Lattice data block handler.

Lattices are 3D control cages used by the Lattice modifier and as
deformation primitives. Synced fields:
  - resolution (points_u/v/w)
  - interpolation type per axis
  - per-point co_deform (the "deformed" position in lattice space)
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


class LatticeCategoryHandler:
    category_name = "lattice"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.lattices):
            lat = bpy.data.lattices.get(name)
            if lat is None:
                continue
            ops.append(self._serialize(lat))
        return ops

    def _serialize(self, lat) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": lat.name,
            "points_u": int(lat.points_u),
            "points_v": int(lat.points_v),
            "points_w": int(lat.points_w),
            "interpolation_type_u": getattr(lat, "interpolation_type_u", "KEY_LINEAR"),
            "interpolation_type_v": getattr(lat, "interpolation_type_v", "KEY_LINEAR"),
            "interpolation_type_w": getattr(lat, "interpolation_type_w", "KEY_LINEAR"),
            "use_outside": bool(getattr(lat, "use_outside", False)),
        }
        n = len(lat.points)
        if _HAS_NUMPY and n > 0:
            buf = _np.empty(n * 3, dtype=_np.float32)
            try:
                lat.points.foreach_get("co_deform", buf)
                out["co_deform"] = buf.reshape(-1, 3).tolist()
            except Exception:
                pass
        elif n > 0:
            out["co_deform"] = [list(p.co_deform) for p in lat.points]
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
            lat = bpy.data.lattices.get(name)
            if lat is None:
                try:
                    lat = bpy.data.lattices.new(name=name)
                except Exception:
                    continue
            for k in ("points_u", "points_v", "points_w"):
                if k in op and hasattr(lat, k):
                    try:
                        setattr(lat, k, int(op[k]))
                    except Exception:
                        pass
            for k in ("interpolation_type_u", "interpolation_type_v",
                      "interpolation_type_w"):
                if k in op and hasattr(lat, k):
                    try:
                        setattr(lat, k, op[k])
                    except Exception:
                        pass
            if "use_outside" in op and hasattr(lat, "use_outside"):
                try:
                    lat.use_outside = bool(op["use_outside"])
                except Exception:
                    pass
            coords = op.get("co_deform")
            if coords:
                try:
                    if _HAS_NUMPY and len(coords) == len(lat.points):
                        flat = _np.array(coords, dtype=_np.float32).reshape(-1)
                        lat.points.foreach_set("co_deform", flat)
                    else:
                        for i, co in enumerate(coords):
                            if i < len(lat.points) and len(co) >= 3:
                                lat.points[i].co_deform = (
                                    float(co[0]), float(co[1]), float(co[2])
                                )
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(l) for l in bpy.data.lattices]

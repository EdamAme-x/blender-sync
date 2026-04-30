"""Metaball data block handler.

Metaballs are implicit-surface primitives. Synced:
  - resolution (render/viewport)
  - threshold / update_method
  - elements list (type, co, radius, stiffness, use_negative)
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


class MetaballCategoryHandler:
    category_name = "metaball"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.metaballs):
            mb = bpy.data.metaballs.get(name)
            if mb is None:
                continue
            ops.append(self._serialize(mb))
        return ops

    def _serialize(self, mb) -> dict[str, Any]:
        elements = []
        for e in mb.elements:
            elements.append({
                "type": e.type,
                "co": list(e.co),
                "radius": float(getattr(e, "radius", 1.0)),
                "stiffness": float(getattr(e, "stiffness", 2.0)),
                "use_negative": bool(getattr(e, "use_negative", False)),
                "size_x": float(getattr(e, "size_x", 1.0)),
                "size_y": float(getattr(e, "size_y", 1.0)),
                "size_z": float(getattr(e, "size_z", 1.0)),
                "rotation": list(getattr(e, "rotation", [0, 0, 0, 1])),
            })
        return {
            "name": mb.name,
            "resolution": float(getattr(mb, "resolution", 0.4)),
            "render_resolution": float(getattr(mb, "render_resolution", 0.2)),
            "threshold": float(getattr(mb, "threshold", 0.6)),
            "update_method": getattr(mb, "update_method", "UPDATE_ALWAYS"),
            "elements": elements,
        }

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            name = op.get("name", "")
            if not name:
                continue
            mb = bpy.data.metaballs.get(name)
            if mb is None:
                try:
                    mb = bpy.data.metaballs.new(name)
                except Exception:
                    continue
            for k in ("resolution", "render_resolution", "threshold"):
                if k in op and hasattr(mb, k):
                    try:
                        setattr(mb, k, float(op[k]))
                    except Exception:
                        pass
            if "update_method" in op and hasattr(mb, "update_method"):
                try:
                    mb.update_method = op["update_method"]
                except Exception:
                    pass

            elements = op.get("elements") or []
            try:
                while len(mb.elements) > 0:
                    mb.elements.remove(mb.elements[0])
                for ed in elements:
                    el = mb.elements.new(type=ed.get("type", "BALL"))
                    co = ed.get("co") or [0, 0, 0]
                    if len(co) >= 3:
                        el.co = (float(co[0]), float(co[1]), float(co[2]))
                    for k in ("radius", "stiffness", "size_x", "size_y", "size_z"):
                        if k in ed and hasattr(el, k):
                            try:
                                setattr(el, k, float(ed[k]))
                            except Exception:
                                pass
                    if "use_negative" in ed and hasattr(el, "use_negative"):
                        try:
                            el.use_negative = bool(ed["use_negative"])
                        except Exception:
                            pass
                    rot = ed.get("rotation")
                    if rot and hasattr(el, "rotation"):
                        try:
                            el.rotation = tuple(float(v) for v in rot)
                        except Exception:
                            pass
            except Exception:
                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(m) for m in bpy.data.metaballs]

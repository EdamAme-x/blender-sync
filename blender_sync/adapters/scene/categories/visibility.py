"""Object visibility handler.

Synchronizes:
  - hide_viewport / hide_render / hide_select
  - show_in_front / display_type
  - Ray visibility (visible_camera/diffuse/glossy/transmission/volume_scatter/shadow)
  - Per-View-Layer layer_collection.exclude / hide_viewport via the
    *active* view layer (multi-layer support is out of scope; the active
    layer is what most users see).
"""
from __future__ import annotations

from typing import Any


_RAY_VIS = [
    "visible_camera", "visible_diffuse", "visible_glossy",
    "visible_transmission", "visible_volume_scatter", "visible_shadow",
]


class VisibilityCategoryHandler:
    category_name = "visibility"

    def collect_dirty(self, dirty_obj_names: set) -> list[dict[str, Any]]:
        return self._collect(dirty_obj_names)

    def collect(self, ctx) -> list[dict[str, Any]]:
        return self._collect(ctx.objects_visibility)

    def _collect(self, names) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(names):
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            ops.append(self._serialize(obj))
        return ops

    def _serialize(self, obj) -> dict[str, Any]:
        out: dict[str, Any] = {
            "n": obj.name,
            "hide_viewport": bool(obj.hide_viewport),
            "hide_render": bool(obj.hide_render),
            "hide_select": bool(obj.hide_select),
        }
        for k in ("show_in_front", "display_type"):
            if hasattr(obj, k):
                try:
                    val = getattr(obj, k)
                    if isinstance(val, (int, float, bool, str)):
                        out[k] = val
                except Exception:
                    pass
        for k in _RAY_VIS:
            if hasattr(obj, k):
                try:
                    out[k] = bool(getattr(obj, k))
                except Exception:
                    pass

        # Active view layer's exclusion / per-layer hide (best-effort)
        try:
            import bpy
            view_layer = bpy.context.view_layer
            if view_layer is not None:
                lc = self._find_layer_collection_for_object(
                    view_layer.layer_collection, obj
                )
                if lc is not None:
                    out["layer_exclude"] = bool(lc.exclude)
                    out["layer_hide_viewport"] = bool(lc.hide_viewport)
        except Exception:
            pass
        return out

    def _find_layer_collection_for_object(self, root_lc, obj):
        # Walk the layer_collection tree and return the first layer_collection
        # whose .collection contains the object.
        try:
            if any(o is obj for o in root_lc.collection.objects):
                return root_lc
            for child in root_lc.children:
                hit = self._find_layer_collection_for_object(child, obj)
                if hit is not None:
                    return hit
        except Exception:
            pass
        return None

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("n", ""))
            if obj is None:
                continue
            for k in ("hide_viewport", "hide_render", "hide_select",
                      "show_in_front"):
                if k in op:
                    try:
                        setattr(obj, k, bool(op[k]))
                    except Exception:
                        pass
            if "display_type" in op:
                try:
                    obj.display_type = op["display_type"]
                except Exception:
                    pass
            for k in _RAY_VIS:
                if k in op and hasattr(obj, k):
                    try:
                        setattr(obj, k, bool(op[k]))
                    except Exception:
                        pass

            # Per-view-layer exclusion.
            try:
                view_layer = bpy.context.view_layer
                if view_layer is not None:
                    lc = self._find_layer_collection_for_object(
                        view_layer.layer_collection, obj
                    )
                    if lc is not None:
                        if "layer_exclude" in op:
                            try:
                                lc.exclude = bool(op["layer_exclude"])
                            except Exception:
                                pass
                        if "layer_hide_viewport" in op:
                            try:
                                lc.hide_viewport = bool(op["layer_hide_viewport"])
                            except Exception:
                                pass
            except Exception:
                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(o) for o in bpy.data.objects]

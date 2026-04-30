"""Camera datablock handler.

Synchronizes camera-specific properties (lens, sensor, dof, clip) for any
Object whose data is a bpy.types.Camera. Object transform is handled by
TransformCategoryHandler — this handler is purely the camera datablock.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
from .base import DirtyContext


_CAMERA_FIELDS = [
    "type", "lens", "lens_unit", "ortho_scale",
    "sensor_fit", "sensor_width", "sensor_height",
    "shift_x", "shift_y",
    "clip_start", "clip_end",
    "passepartout_alpha", "show_passepartout",
]

_DOF_FIELDS = [
    "use_dof", "focus_distance", "aperture_fstop",
    "aperture_blades", "aperture_rotation", "aperture_ratio",
]


class CameraCategoryHandler:
    category_name = "camera"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.cameras):
            cam = bpy.data.cameras.get(name)
            if cam is None:
                continue
            ops.append(self._serialize(cam))
        return ops

    def _serialize(self, cam) -> dict[str, Any]:
        out: dict[str, Any] = {"name": cam.name, "props": {}, "dof": {}}
        for f in _CAMERA_FIELDS:
            if not hasattr(cam, f):
                continue
            try:
                val = getattr(cam, f)
                if isinstance(val, (int, float, bool, str)):
                    out["props"][f] = val
            except Exception:
                pass
        if hasattr(cam, "dof"):
            for f in _DOF_FIELDS:
                if hasattr(cam.dof, f):
                    try:
                        val = getattr(cam.dof, f)
                        if isinstance(val, (int, float, bool, str)):
                            out["dof"][f] = val
                    except Exception:
                        pass
            focus_obj = getattr(cam.dof, "focus_object", None)
            if focus_obj is not None:
                ref = _datablock_ref.try_ref(focus_obj)
                if ref:
                    out["dof"]["focus_object"] = ref

        # Background images (image-only; image data block is shared via
        # the IMAGE category and resolved by name here).
        bgs = []
        for bg in getattr(cam, "background_images", []) or []:
            entry: dict[str, Any] = {
                "alpha": float(getattr(bg, "alpha", 1.0)),
                "show_background_image": bool(getattr(bg, "show_background_image", True)),
                "frame_method": getattr(bg, "frame_method", "FIT"),
                "display_depth": getattr(bg, "display_depth", "BACK"),
            }
            img = getattr(bg, "image", None)
            if img is not None:
                ref = _datablock_ref.try_ref(img)
                if ref:
                    entry["image"] = ref
            bgs.append(entry)
        if bgs:
            out["background_images"] = bgs
        try:
            out["show_background_images"] = bool(cam.show_background_images)
        except Exception:
            pass
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            cam = bpy.data.cameras.get(op.get("name", ""))
            if cam is None:
                continue
            for k, v in (op.get("props") or {}).items():
                if hasattr(cam, k):
                    try:
                        setattr(cam, k, v)
                    except Exception:
                        pass
            if hasattr(cam, "dof"):
                for k, v in (op.get("dof") or {}).items():
                    if k == "focus_object":
                        if _datablock_ref.is_ref(v):
                            resolved = _datablock_ref.resolve_ref(v)
                            if resolved is not None:
                                try:
                                    cam.dof.focus_object = resolved
                                except Exception:
                                    pass
                        continue
                    if hasattr(cam.dof, k):
                        try:
                            setattr(cam.dof, k, v)
                        except Exception:
                            pass

            bgs = op.get("background_images") or []
            if bgs is not None and hasattr(cam, "background_images"):
                try:
                    cam.background_images.clear()
                except Exception:
                    pass
                for entry in bgs:
                    try:
                        bg = cam.background_images.new()
                    except Exception:
                        continue
                    img_ref = entry.get("image")
                    if img_ref:
                        img = _datablock_ref.resolve_ref(img_ref)
                        if img is not None:
                            try:
                                bg.image = img
                            except Exception:
                                pass
                    for k in ("alpha", "show_background_image",
                              "frame_method", "display_depth"):
                        if k in entry and hasattr(bg, k):
                            try:
                                setattr(bg, k, entry[k])
                            except Exception:
                                pass
            if "show_background_images" in op and hasattr(cam, "show_background_images"):
                try:
                    cam.show_background_images = bool(op["show_background_images"])
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(c) for c in bpy.data.cameras]

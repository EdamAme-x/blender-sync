"""Image datablock handler (path-based, no binary transfer).

Synchronizes the metadata of bpy.data.images:
  - filepath (absolute or //relative)
  - source (FILE / GENERATED / MOVIE / SEQUENCE)
  - colorspace settings
  - alpha mode

This lets a peer set up the same image references when both have access
to the file via shared storage / cloud / git-lfs. Binary transfer of the
pixel buffer is out of scope for the current phase.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


_FIELDS = [
    "filepath", "source", "alpha_mode",
    "use_view_as_render", "use_deinterlace",
]


class ImageCategoryHandler:
    category_name = "image"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.images):
            img = bpy.data.images.get(name)
            if img is None:
                continue
            ops.append(self._serialize(img))
        return ops

    def _serialize(self, img) -> dict[str, Any]:
        out: dict[str, Any] = {"name": img.name, "props": {}}
        for f in _FIELDS:
            if hasattr(img, f):
                try:
                    val = getattr(img, f)
                    if isinstance(val, (int, float, bool, str)):
                        out["props"][f] = val
                except Exception:
                    pass
        if hasattr(img, "colorspace_settings") and img.colorspace_settings:
            try:
                out["colorspace"] = str(img.colorspace_settings.name)
            except Exception:
                pass

        # GENERATED-source images: dimensions / fill color / type.
        if getattr(img, "source", "") == "GENERATED":
            for k in ("generated_width", "generated_height",
                      "generated_type"):
                if hasattr(img, k):
                    try:
                        v = getattr(img, k)
                        if isinstance(v, (int, float, bool, str)):
                            out[k] = v
                    except Exception:
                        pass
            try:
                out["generated_color"] = list(img.generated_color)
            except Exception:
                pass

        # Note about packed (binary) images — we only mark them so a
        # peer can warn that this image needs file sharing.
        try:
            if img.packed_file is not None:
                out["packed"] = True
        except Exception:
            pass
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
            img = bpy.data.images.get(name)
            if img is None:
                # Try to load from filepath; otherwise create with the
                # generated settings the sender provided so we don't end
                # up with an 8x8 placeholder.
                fp = (op.get("props") or {}).get("filepath")
                if fp:
                    try:
                        img = bpy.data.images.load(fp, check_existing=True)
                        if img.name != name:
                            img.name = name
                    except Exception:
                        img = None
                if img is None:
                    w = int(op.get("generated_width", 8))
                    h = int(op.get("generated_height", 8))
                    try:
                        img = bpy.data.images.new(name=name, width=w, height=h)
                    except Exception:
                        continue
                    for k in ("generated_type",):
                        if k in op and hasattr(img, k):
                            try:
                                setattr(img, k, op[k])
                            except Exception:
                                pass
                    gc = op.get("generated_color")
                    if gc and hasattr(img, "generated_color"):
                        try:
                            img.generated_color = tuple(float(c) for c in gc)
                        except Exception:
                            pass
            for k, v in (op.get("props") or {}).items():
                if hasattr(img, k):
                    try:
                        setattr(img, k, v)
                    except Exception:
                        pass
            cs = op.get("colorspace")
            if cs and hasattr(img, "colorspace_settings"):
                try:
                    img.colorspace_settings.name = cs
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(i) for i in bpy.data.images]

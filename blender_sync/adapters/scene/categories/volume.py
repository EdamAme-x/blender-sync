"""Volume data block handler.

OpenVDB volumes are external files that Blender references. We only sync
the reference (filepath) plus playback parameters; the actual VDB bytes
are not transferred (they're typically too large for a DataChannel).

Peers must already have the VDB file at the same path for the volume to
display — this is the same constraint as image textures referenced by
filepath.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


class VolumeCategoryHandler:
    category_name = "volume"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.volumes):
            vol = bpy.data.volumes.get(name)
            if vol is None:
                continue
            ops.append(self._serialize(vol))
        return ops

    def _serialize(self, vol) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": vol.name,
            "filepath": getattr(vol, "filepath", ""),
            "frame_start": int(getattr(vol, "frame_start", 1)),
            "frame_offset": int(getattr(vol, "frame_offset", 0)),
            "frame_duration": int(getattr(vol, "frame_duration", 0)),
            "sequence_mode": getattr(vol, "sequence_mode", "REPEAT"),
            "is_sequence": bool(getattr(vol, "is_sequence", False)),
        }
        # Display settings (4.x)
        display = getattr(vol, "display", None)
        if display is not None:
            try:
                out["display"] = {
                    "wireframe_type": getattr(display, "wireframe_type", "BOXES"),
                    "wireframe_detail": getattr(display, "wireframe_detail", "COARSE"),
                    "interpolation_method": getattr(display, "interpolation_method", "LINEAR"),
                    "density": float(getattr(display, "density", 1.0)),
                }
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
            vol = bpy.data.volumes.get(name)
            if vol is None:
                try:
                    vol = bpy.data.volumes.new(name)
                except Exception:
                    continue
            if "filepath" in op and hasattr(vol, "filepath"):
                try:
                    vol.filepath = op["filepath"]
                except Exception:
                    pass
            for k in ("frame_start", "frame_offset", "frame_duration"):
                if k in op and hasattr(vol, k):
                    try:
                        setattr(vol, k, int(op[k]))
                    except Exception:
                        pass
            if "sequence_mode" in op and hasattr(vol, "sequence_mode"):
                try:
                    vol.sequence_mode = op["sequence_mode"]
                except Exception:
                    pass
            display_op = op.get("display") or {}
            display = getattr(vol, "display", None)
            if display is not None and display_op:
                for k in ("wireframe_type", "wireframe_detail", "interpolation_method"):
                    if k in display_op and hasattr(display, k):
                        try:
                            setattr(display, k, display_op[k])
                        except Exception:
                            pass
                if "density" in display_op and hasattr(display, "density"):
                    try:
                        display.density = float(display_op["density"])
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        vols = getattr(bpy.data, "volumes", None)
        if vols is None:
            return []
        return [self._serialize(v) for v in vols]

"""3D viewport shading state handler.

Synchronizes the active 3D viewport's shading mode (SOLID / MATERIAL /
RENDERED / WIREFRAME) and a handful of related toggles. Without this
peers see the same scene data but very different rendering of it,
which feels broken even when nothing is actually divergent.

Rides the FAST channel — viewport shading flips are interactive UI
gestures, not data the receiver needs reliably.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .base import DirtyContext

_SHADING_FIELDS = (
    "type",
    "light",
    "studio_light",
    "color_type",
    "single_color",
    "background_type",
    "background_color",
    "show_xray",
    "xray_alpha",
    "show_shadows",
    "show_cavity",
    "use_dof",
    "use_scene_lights",
    "use_scene_world",
    "use_scene_lights_render",
    "use_scene_world_render",
)


class View3DCategoryHandler:
    category_name = "view3d"

    def __init__(self) -> None:
        self._sent_hash: str | None = None

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        space = self._find_active_view3d(bpy)
        if space is None:
            return []
        op = self._serialize(space)
        digest = self._hash(op)
        if digest == self._sent_hash:
            return []
        self._sent_hash = digest
        return [op]

    def _hash(self, op: dict[str, Any]) -> str:
        try:
            payload = json.dumps(op, sort_keys=True, default=str)
        except Exception:
            payload = repr(op)
        return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()

    def _find_active_view3d(self, bpy):
        # First look in the current screen, then fall back to the first
        # 3D view encountered across all windows.
        screen = getattr(bpy.context, "screen", None)
        candidates = []
        if screen is not None:
            candidates.append(screen)
        for win in getattr(bpy.context.window_manager, "windows", []):
            scr = getattr(win, "screen", None)
            if scr is not None and scr is not screen:
                candidates.append(scr)
        for scr in candidates:
            for area in getattr(scr, "areas", []):
                if getattr(area, "type", "") != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if getattr(space, "type", "") == "VIEW_3D":
                        return space
        return None

    def _serialize(self, space) -> dict[str, Any]:
        out: dict[str, Any] = {}
        shading = getattr(space, "shading", None)
        if shading is None:
            return out
        s_out: dict[str, Any] = {}
        for k in _SHADING_FIELDS:
            if not hasattr(shading, k):
                continue
            try:
                v = getattr(shading, k)
            except Exception:
                continue
            if isinstance(v, (int, float, bool, str)):
                s_out[k] = v
            elif hasattr(v, "__iter__") and not isinstance(v, str):
                try:
                    s_out[k] = [float(x) for x in v]
                except Exception:
                    pass
        if s_out:
            out["shading"] = s_out
        # Overlay toggle — frequently part of "are we looking at the
        # same thing" ambiguity.
        overlay = getattr(space, "overlay", None)
        if overlay is not None:
            o_out: dict[str, Any] = {}
            for k in ("show_overlays", "show_floor", "show_axis_x",
                      "show_axis_y", "show_axis_z", "show_relationship_lines"):
                if hasattr(overlay, k):
                    try:
                        o_out[k] = bool(getattr(overlay, k))
                    except Exception:
                        pass
            if o_out:
                out["overlay"] = o_out
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        space = self._find_active_view3d(bpy)
        if space is None:
            return
        for op in ops:
            shading = getattr(space, "shading", None)
            if shading is not None:
                for k, v in (op.get("shading") or {}).items():
                    if not hasattr(shading, k):
                        continue
                    try:
                        cur = getattr(shading, k)
                        if isinstance(cur, bool):
                            setattr(shading, k, bool(v))
                        elif isinstance(cur, (int, float)):
                            setattr(shading, k, type(cur)(v))
                        elif hasattr(cur, "__iter__") and hasattr(v, "__iter__"):
                            setattr(shading, k, tuple(float(x) for x in v))
                        else:
                            setattr(shading, k, v)
                    except Exception:
                        pass
            overlay = getattr(space, "overlay", None)
            if overlay is not None:
                for k, v in (op.get("overlay") or {}).items():
                    if not hasattr(overlay, k):
                        continue
                    try:
                        setattr(overlay, k, bool(v))
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        space = self._find_active_view3d(bpy)
        if space is None:
            return []
        return [self._serialize(space)]

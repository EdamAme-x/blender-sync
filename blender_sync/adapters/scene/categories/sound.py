"""Sound datablock handler.

Synchronizes the metadata of bpy.data.sounds:
  - filepath (absolute or //relative)
  - use_memory_cache, use_mono

Like Image, this lets peers reference the same audio file when both
have it on shared storage. Audio bytes are not transferred — those
files are typically megabytes and the DataChannel is not the right
transport for them.

Sound datablocks are referenced by VSE SoundStrips (`strip.sound`) and
Speaker objects (`speaker.sound`). The VSE handler already encodes the
strip's `sound` reference by name; this handler ensures the underlying
datablock exists on the peer with the correct filepath.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


_FIELDS = (
    "filepath",
    "use_memory_cache",
    "use_mono",
)


class SoundCategoryHandler:
    category_name = "sound"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.sounds):
            snd = bpy.data.sounds.get(name)
            if snd is None:
                continue
            ops.append(self._serialize(snd))
        return ops

    def _serialize(self, snd) -> dict[str, Any]:
        out: dict[str, Any] = {"name": snd.name, "props": {}}
        for f in _FIELDS:
            if not hasattr(snd, f):
                continue
            try:
                v = getattr(snd, f)
            except Exception:
                continue
            if isinstance(v, (int, float, bool, str)):
                out["props"][f] = v
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
            snd = bpy.data.sounds.get(name)
            if snd is None:
                # Sound datablock creation requires a filepath up-front
                # (`bpy.data.sounds.load(filepath, check_existing=True)`).
                # If we don't have one, defer — VSE strip apply will
                # call `new_sound(...)` which creates the datablock as
                # a side effect.
                fp = (op.get("props") or {}).get("filepath")
                if not fp:
                    continue
                try:
                    snd = bpy.data.sounds.load(fp, check_existing=True)
                except Exception:
                    continue
                if snd.name != name:
                    self._rename_into(bpy, snd, name)
            for k, v in (op.get("props") or {}).items():
                if not hasattr(snd, k):
                    continue
                try:
                    cur = getattr(snd, k)
                    if isinstance(cur, bool):
                        setattr(snd, k, bool(v))
                    elif isinstance(cur, (int, float)):
                        setattr(snd, k, type(cur)(v))
                    else:
                        setattr(snd, k, v)
                except Exception:
                    pass

    def _rename_into(self, bpy, snd, target_name: str) -> None:
        """Rename `snd` to `target_name`. If another Sound already owns
        that name, push it to a uid-suffixed temp first so Blender
        doesn't silently append `.001` to ours and leave the wire and
        local names diverged.
        """
        existing = bpy.data.sounds.get(target_name)
        if existing is not None and existing is not snd:
            # 6-char filename hash is enough — collisions astronomically
            # unlikely, no uid stamping needed for a transient name.
            tmp = f"{target_name}.bsync_tmp_{abs(hash(snd.filepath)) & 0xffffff:06x}"
            try:
                existing.name = tmp
            except Exception:
                return
        try:
            snd.name = target_name
        except Exception:
            pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        sounds = getattr(bpy.data, "sounds", None)
        if sounds is None:
            return []
        return [self._serialize(s) for s in sounds]

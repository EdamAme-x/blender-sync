"""Shape Keys handler.

Each shape-keyable Object (Mesh, Lattice, Curve) can have a Key data
block with multiple key_blocks (basis + morph targets). We serialize:
  - key block names + values (slider position)
  - vertex coordinates per block (full snapshot — small for typical
    facial rigs; large for hi-poly characters)
  - relative_key (parent block) by name
  - vertex_group, mute, slider_min/max

For hi-poly meshes the "data" payload becomes large. We hash the
per-block coords and only resend on actual change (similar to the mesh
handler's strategy).
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


class ShapeKeysCategoryHandler:
    category_name = "shape_keys"

    def __init__(self) -> None:
        self._sent_block_hashes: dict[tuple[str, str], str] = {}

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.shape_keys):
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            entry = self._serialize(obj)
            if entry is not None:
                ops.append(entry)
        return ops

    def _serialize(self, obj) -> dict[str, Any] | None:
        data = obj.data
        if data is None or not hasattr(data, "shape_keys") or data.shape_keys is None:
            return None
        keys = data.shape_keys
        blocks: list[dict[str, Any]] = []
        for kb in keys.key_blocks:
            block_hash = self._hash_block(kb)
            entry: dict[str, Any] = {
                "name": kb.name,
                "value": float(kb.value),
                "mute": bool(kb.mute),
                "slider_min": float(kb.slider_min),
                "slider_max": float(kb.slider_max),
                "vertex_group": str(kb.vertex_group or ""),
                "relative_key": kb.relative_key.name if kb.relative_key else None,
                "hash": block_hash,
            }
            # Interpolation curve between value=0 and value=1 (4.x).
            interp = getattr(kb, "interpolation", None)
            if isinstance(interp, str):
                entry["interpolation"] = interp
            cache_key = (obj.name, kb.name)
            if self._sent_block_hashes.get(cache_key) != block_hash:
                entry["coords"] = self._extract_coords(kb)
                self._sent_block_hashes[cache_key] = block_hash
            blocks.append(entry)
        return {
            "obj": obj.name,
            "use_relative": bool(getattr(keys, "use_relative", True)),
            "blocks": blocks,
        }

    def _extract_coords(self, kb) -> list[list[float]]:
        n = len(kb.data)
        if _HAS_NUMPY and n > 0:
            buf = _np.empty(n * 3, dtype=_np.float32)
            kb.data.foreach_get("co", buf)
            return buf.reshape(-1, 3).tolist()
        return [list(d.co) for d in kb.data]

    def _hash_block(self, kb) -> str:
        n = len(kb.data)
        h = hashlib.blake2b(digest_size=8)
        if _HAS_NUMPY and n > 0:
            buf = _np.empty(n * 3, dtype=_np.float32)
            kb.data.foreach_get("co", buf)
            h.update(buf.tobytes())
        else:
            for d in kb.data:
                h.update(bytes(repr(tuple(d.co)), "ascii"))
        return h.hexdigest()

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or obj.data is None:
                continue
            self._apply_object(bpy, obj, op)

    def _apply_object(self, bpy, obj, op: dict) -> None:
        keys = obj.data.shape_keys
        if keys is None:
            try:
                obj.shape_key_add(name="Basis")
                keys = obj.data.shape_keys
            except Exception:
                return

        keys.use_relative = bool(op.get("use_relative", True))
        target_blocks = op.get("blocks") or []
        target_names = {b["name"] for b in target_blocks}

        # Remove blocks not in target.
        for kb in list(keys.key_blocks):
            if kb.name not in target_names:
                try:
                    obj.shape_key_remove(kb)
                except Exception:
                    pass

        # Add / update blocks.
        for bd in target_blocks:
            kb = keys.key_blocks.get(bd["name"])
            if kb is None:
                try:
                    kb = obj.shape_key_add(name=bd["name"])
                except Exception:
                    continue
            for k in ("value", "slider_min", "slider_max"):
                if k in bd:
                    try:
                        setattr(kb, k, float(bd[k]))
                    except Exception:
                        pass
            if "mute" in bd:
                try:
                    kb.mute = bool(bd["mute"])
                except Exception:
                    pass
            vg = bd.get("vertex_group")
            if vg is not None:
                try:
                    kb.vertex_group = vg
                except Exception:
                    pass
            interp = bd.get("interpolation")
            if interp is not None and hasattr(kb, "interpolation"):
                try:
                    kb.interpolation = interp
                except Exception:
                    pass
            rk = bd.get("relative_key")
            if rk:
                ref = keys.key_blocks.get(rk)
                if ref is not None:
                    try:
                        kb.relative_key = ref
                    except Exception:
                        pass
            coords = bd.get("coords")
            if coords:
                try:
                    if _HAS_NUMPY and len(coords) == len(kb.data):
                        flat = _np.array(coords, dtype=_np.float32).reshape(-1)
                        kb.data.foreach_set("co", flat)
                    else:
                        for i, co in enumerate(coords):
                            if i < len(kb.data) and len(co) >= 3:
                                kb.data[i].co = (
                                    float(co[0]), float(co[1]), float(co[2])
                                )
                except Exception:
                    pass
            h = bd.get("hash")
            if h:
                self._sent_block_hashes[(obj.name, bd["name"])] = h

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            entry = self._serialize(obj)
            if entry is not None:
                out.append(entry)
        return out

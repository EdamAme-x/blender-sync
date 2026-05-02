"""Object material slots handler.

Material slots define which materials an object has and in what order.
Mesh polygons reference materials by their slot index, so this handler
must run BEFORE mesh apply on the receiver to keep face material_index
references valid. See bpy_scene_gateway for the apply ordering.

This handler piggybacks on the transform dirty set: any object update
implies its material_slots could have changed (assignment is fast and
indistinguishable from other Object updates in depsgraph).
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


class MaterialSlotsCategoryHandler:
    """Synchronizes Object.material_slots ordering and assignment."""

    category_name = "material_slots"

    def __init__(self) -> None:
        # Per-object "last observed slot count" — covers BOTH outgoing
        # serialize and incoming apply. We need to suppress the
        # empty-slot clear-op only when the object has never had
        # slots from any source, otherwise:
        #   - serialize-only update misses the case where peer sent
        #     us slots, we received them, then local user cleared
        #     them. If we don't bump the counter on apply, our
        #     subsequent serialize sees cur=0/last=0 and suppresses
        #     the legitimate clear-op, leaving the original peer
        #     stuck on the stale stack.
        # Counter is touched whenever a non-empty op is observed
        # (collect or apply); only the empty-with-no-prior case is
        # suppressed.
        self._last_seen_count: dict[str, int] = {}

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.objects_transform):
            obj = bpy.data.objects.get(name)
            if obj is None or not hasattr(obj, "material_slots"):
                continue
            entry = self._serialize(obj)
            if entry is not None:
                ops.append(entry)
        return ops

    def _serialize(self, obj):
        slots = [
            {
                "material": slot.material.name if slot.material else None,
                "link": slot.link,  # 'OBJECT' or 'DATA'
            }
            for slot in obj.material_slots
        ]
        cur_n = len(slots)
        # Suppress emit when the object has no slots AND we never
        # sent a non-empty list for it. Otherwise transform-only
        # edits would broadcast an empty clear-op and wipe peers'
        # slots for un-slotted objects on our side. Once we've sent
        # a non-empty list, the next empty list IS a real "user
        # cleared the stack" event and must propagate.
        if cur_n == 0 and self._last_seen_count.get(obj.name, 0) == 0:
            return None
        self._last_seen_count[obj.name] = cur_n
        return {"obj": obj.name, "slots": slots}

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj_name = op.get("obj", "")
            obj = bpy.data.objects.get(obj_name)
            if obj is None or not hasattr(obj, "material_slots"):
                continue
            target_slots = op.get("slots") or []
            # Record the post-apply slot count so a subsequent local
            # clear of these received slots correctly emits an empty
            # clear-op (instead of being suppressed as "first-time
            # empty").
            self._last_seen_count[obj_name] = len(target_slots)
            self._apply_slots(bpy, obj, target_slots)

    def _apply_slots(self, bpy, obj, target_slots: list) -> None:
        # Each target_slot is either a legacy string (old wire format,
        # before slot.link support) or a dict {"material": str|None, "link": str}.
        cur_n = len(obj.material_slots)
        tgt_n = len(target_slots)

        # Resize via DATA list. OBJECT-link slots are still indexed via
        # the same list count; only the per-slot link/material differs.
        if obj.data is not None and hasattr(obj.data, "materials"):
            while cur_n < tgt_n:
                try:
                    obj.data.materials.append(None)
                except Exception:
                    break
                cur_n += 1
            while cur_n > tgt_n:
                try:
                    obj.data.materials.pop(index=cur_n - 1)
                except Exception:
                    break
                cur_n -= 1

        for i, entry in enumerate(target_slots):
            if i >= len(obj.material_slots):
                break
            slot = obj.material_slots[i]

            if isinstance(entry, str) or entry is None:
                mat_name = entry
                link = "DATA"
            else:
                mat_name = entry.get("material")
                link = entry.get("link", "DATA")

            try:
                slot.link = link
            except Exception:
                pass

            if mat_name is None:
                try:
                    slot.material = None
                except Exception:
                    pass
                continue
            mat = bpy.data.materials.get(mat_name)
            if mat is None:
                mat = bpy.data.materials.new(name=mat_name)
            try:
                slot.material = mat
            except Exception:
                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            if not hasattr(obj, "material_slots"):
                continue
            entry = self._serialize(obj)
            if entry is not None:
                out.append(entry)
        return out

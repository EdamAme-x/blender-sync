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
        # Always return an op — empty `slots` means "remove all
        # material slots", required for undo cases where the user
        # cleared the slot list. apply path resizes the slot list
        # down via obj.data.materials.pop, so an empty target works.
        return {"obj": obj.name, "slots": slots}

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or not hasattr(obj, "material_slots"):
                continue
            target_slots = op.get("slots") or []
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

"""Collection handler.

Synchronizes scene collection hierarchy:
  - parent / child collection structure (children's names)
  - object membership (object names per collection)
  - hide_viewport / hide_render / hide_select

Collections are themselves data blocks; we identify them by name.
Object linking changes (drag into a collection) flow through here.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


class CollectionCategoryHandler:
    category_name = "collection"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.collections):
            coll = bpy.data.collections.get(name)
            if coll is None:
                continue
            ops.append(self._serialize(coll))
        return ops

    def _serialize(self, coll) -> dict[str, Any]:
        return {
            "name": coll.name,
            "children": [c.name for c in coll.children],
            "objects": [o.name for o in coll.objects],
            "hide_viewport": bool(getattr(coll, "hide_viewport", False)),
            "hide_render": bool(getattr(coll, "hide_render", False)),
            "hide_select": bool(getattr(coll, "hide_select", False)),
        }

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            self._apply_one(bpy, op)

    def _apply_one(self, bpy, op: dict[str, Any]) -> None:
        name = op.get("name", "")
        if not name:
            return
        coll = bpy.data.collections.get(name)
        if coll is None:
            try:
                coll = bpy.data.collections.new(name)
                bpy.context.scene.collection.children.link(coll)
            except Exception:
                return

        for k in ("hide_viewport", "hide_render", "hide_select"):
            if k in op and hasattr(coll, k):
                try:
                    setattr(coll, k, bool(op[k]))
                except Exception:
                    pass

        target_children = set(op.get("children") or [])
        cur_children = {c.name for c in coll.children}
        for child_name in target_children - cur_children:
            child = bpy.data.collections.get(child_name)
            if child is None:
                continue
            try:
                coll.children.link(child)
            except Exception:
                pass
        for child_name in cur_children - target_children:
            child = bpy.data.collections.get(child_name)
            if child is None or child not in coll.children.values():
                continue
            try:
                coll.children.unlink(child)
            except Exception:
                pass

        target_objs = set(op.get("objects") or [])
        cur_objs = {o.name for o in coll.objects}
        for obj_name in target_objs - cur_objs:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                continue
            try:
                coll.objects.link(obj)
            except Exception:
                pass
        for obj_name in cur_objs - target_objs:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                continue
            try:
                coll.objects.unlink(obj)
            except Exception:
                pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(c) for c in bpy.data.collections]

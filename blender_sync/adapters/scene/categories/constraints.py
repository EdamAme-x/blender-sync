"""Object constraints handler.

Synchronizes Object.constraints (Copy Location / Track To / Limit
Distance / Shrinkwrap / IK / Follow Path / Child Of, etc.). Pose-bone
constraints are owned by the PoseCategoryHandler.

Constraints often hold pointer-typed properties (target Object, target
Mesh for Shrinkwrap, follow-path Curve, etc.). We use the shared
datablock-ref encoder so they survive the wire and resolve on the
receiver via the modifier's `_resolve_ref`.

Receiver always tears down + recreates the constraint stack to keep
order deterministic. Constraints are typically few per object so this
isn't a performance issue.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
from .base import DirtyContext

_PRIM = (int, float, bool, str)

_CONSTRAINT_PROP_BLACKLIST = {
    "rna_type", "bl_rna", "name", "type", "is_valid", "error_location",
    "error_rotation",
}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, _PRIM):
        return value
    ref = _datablock_ref.try_ref(value)
    if ref is not None:
        return ref
    if hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            out = []
            for v in value:
                if isinstance(v, _PRIM):
                    out.append(v)
                else:
                    return None
            return out
        except Exception:
            return None
    return None


class ConstraintsCategoryHandler:
    category_name = "constraints"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.objects_transform):
            obj = bpy.data.objects.get(name)
            if obj is None or not hasattr(obj, "constraints"):
                continue
            entry = self._serialize(obj)
            if entry is not None:
                ops.append(entry)
        return ops

    def _serialize(self, obj) -> dict[str, Any] | None:
        # Always return an op (even with an empty constraints list)
        # so that an undo step which cleared all constraints reaches
        # peers. Apply rebuilds the stack from this list, so an empty
        # list = "remove all constraints".
        if not hasattr(obj, "constraints"):
            return None
        constraints = []
        for c in obj.constraints:
            cd: dict[str, Any] = {
                "name": c.name,
                "type": c.type,
                "props": {},
            }
            for attr in dir(c):
                if attr.startswith("_") or attr in _CONSTRAINT_PROP_BLACKLIST:
                    continue
                try:
                    val = getattr(c, attr)
                except Exception:
                    continue
                if callable(val):
                    continue
                ser = _serialize_value(val)
                if ser is not None:
                    cd["props"][attr] = ser
            constraints.append(cd)
        return {"obj": obj.name, "constraints": constraints}

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or not hasattr(obj, "constraints"):
                continue
            self._apply_object(bpy, obj, op.get("constraints") or [])

    def _apply_object(self, bpy, obj, constraints: list[dict]) -> None:
        # Tear down + rebuild for deterministic ordering.
        try:
            for c in list(obj.constraints):
                obj.constraints.remove(c)
        except Exception:
            pass
        for cd in constraints:
            ctype = cd.get("type")
            cname = cd.get("name")
            if not ctype or not cname:
                continue
            try:
                c = obj.constraints.new(type=ctype)
                c.name = cname
            except Exception:
                continue
            for k, v in (cd.get("props") or {}).items():
                if not hasattr(c, k):
                    continue
                if _datablock_ref.is_ref(v):
                    resolved = _datablock_ref.resolve_ref(v)
                    if resolved is None:
                        continue
                    try:
                        setattr(c, k, resolved)
                    except Exception:
                        pass
                    continue
                try:
                    setattr(c, k, v)
                except Exception:
                    pass

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

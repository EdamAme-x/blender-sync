"""Modifier stack handler.

Serializes the full modifier stack of an object: ordered list of (name, type,
visibility flags, all native Blender properties).

Applying recreates the stack from scratch (delete all -> add in order ->
set properties).  This avoids ambiguity when a modifier is reordered.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref

_PRIM = (int, float, bool, str)

_MOD_PROP_BLACKLIST = {
    "rna_type", "bl_rna", "name", "type", "is_active",
}

# Physics modifiers store almost all of their interesting state in
# nested settings structs, not directly on the modifier. The walk in
# `_serialize_modifier` flattens these into a sibling dict so peers can
# round-trip without us having to enumerate every individual property.
_NESTED_SETTINGS_ATTRS = (
    "settings",            # Cloth, SoftBody, Particle (PARTICLE_SYSTEM)
    "collision_settings",  # Cloth
    "domain_settings",     # Fluid (DOMAIN)
    "flow_settings",       # Fluid (FLOW)
    "effector_settings",   # Fluid (EFFECTOR)
    "point_cache",         # Cloth/SoftBody — playback range only, not bake data
    "rest_source",         # SoftBody alt rest geometry
)

_NESTED_PROP_BLACKLIST = {
    "rna_type", "bl_rna",
    # Skip baked / cached data — far too large for the wire and not
    # reproducible across machines anyway. Peers re-bake locally.
    "data", "data_types", "info",
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


class ModifierCategoryHandler:
    category_name = "modifier"

    def __init__(
        self, retry_queue: _datablock_ref.ReferenceResolutionQueue | None = None
    ) -> None:
        self._retry_queue = retry_queue

    def collect_dirty(self, dirty_obj_names: set) -> list[dict[str, Any]]:
        return self._collect(dirty_obj_names)

    def collect(self, ctx) -> list[dict[str, Any]]:
        # Retry any references that failed to resolve on a previous apply.
        if self._retry_queue is not None:
            try:
                self._retry_queue.retry()
            except Exception:
                pass
        return self._collect(ctx.modifiers)

    def _collect(self, names) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(names):
            obj = bpy.data.objects.get(name)
            if obj is None or not hasattr(obj, "modifiers"):
                continue
            ops.append(self._serialize_object(obj))
        return ops

    def _serialize_object(self, obj) -> dict[str, Any]:
        return {
            "obj": obj.name,
            "modifiers": [self._serialize_modifier(m) for m in obj.modifiers],
        }

    def _serialize_modifier(self, mod) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": mod.name,
            "type": mod.type,
        }
        props: dict[str, Any] = {}
        nested: dict[str, dict[str, Any]] = {}
        for attr in dir(mod):
            if attr.startswith("_") or attr in _MOD_PROP_BLACKLIST:
                continue
            try:
                val = getattr(mod, attr)
            except Exception:
                continue
            if callable(val):
                continue
            if attr in _NESTED_SETTINGS_ATTRS and val is not None:
                # Walk the nested struct (Cloth settings etc.). The
                # struct itself can't be serialized; its primitive props
                # can.
                inner = self._serialize_struct(val)
                if inner:
                    nested[attr] = inner
                continue
            serialized = (
                val if isinstance(val, _PRIM) else _serialize_value(val)
            )
            if serialized is not None:
                props[attr] = serialized
        out["props"] = props
        if nested:
            out["nested"] = nested
        return out

    def _serialize_struct(self, struct) -> dict[str, Any]:
        """Serialize a single Blender RNA sub-struct one level deep.
        Used for ClothSettings, SoftBodySettings, FluidDomainSettings,
        etc. — anywhere a physics modifier hides its real state."""
        out: dict[str, Any] = {}
        for attr in dir(struct):
            if attr.startswith("_") or attr in _NESTED_PROP_BLACKLIST:
                continue
            try:
                val = getattr(struct, attr)
            except Exception:
                continue
            if callable(val):
                continue
            serialized = (
                val if isinstance(val, _PRIM) else _serialize_value(val)
            )
            if serialized is not None:
                out[attr] = serialized
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or not hasattr(obj, "modifiers"):
                continue
            self._apply_object(obj, op.get("modifiers", []))

    def _apply_object(self, obj, modifiers: list[dict[str, Any]]) -> None:
        for m in list(obj.modifiers):
            try:
                obj.modifiers.remove(m)
            except Exception:
                pass

        for entry in modifiers:
            mtype = entry.get("type")
            mname = entry.get("name")
            if not mtype or not mname:
                continue
            try:
                new_mod = obj.modifiers.new(name=mname, type=mtype)
            except Exception:
                continue
            for k, v in (entry.get("props") or {}).items():
                if not hasattr(new_mod, k):
                    continue
                # Resolve datablock references (Object/NodeTree/etc.)
                if _datablock_ref.is_ref(v):
                    resolved = _datablock_ref.resolve_ref(v)
                    if resolved is None:
                        # Reference target not yet synced; queue for retry.
                        if self._retry_queue is not None:
                            self._retry_queue.add(new_mod, k, v)
                        continue
                    try:
                        setattr(new_mod, k, resolved)
                    except Exception:
                        continue
                    continue
                try:
                    setattr(new_mod, k, v)
                except Exception:
                    continue
            # Nested physics structs (Cloth.settings, Fluid.domain_settings, ...).
            for struct_attr, inner in (entry.get("nested") or {}).items():
                struct = getattr(new_mod, struct_attr, None)
                if struct is None:
                    continue
                self._apply_struct(struct, inner)

    def _apply_struct(self, struct, inner: dict) -> None:
        for k, v in inner.items():
            if not hasattr(struct, k):
                continue
            if _datablock_ref.is_ref(v):
                resolved = _datablock_ref.resolve_ref(v)
                if resolved is None:
                    if self._retry_queue is not None:
                        self._retry_queue.add(struct, k, v)
                    continue
                try:
                    setattr(struct, k, resolved)
                except Exception:
                    continue
                continue
            try:
                setattr(struct, k, v)
            except Exception:
                continue

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            if not hasattr(obj, "modifiers"):
                continue
            if not list(obj.modifiers):
                continue
            out.append(self._serialize_object(obj))
        return out

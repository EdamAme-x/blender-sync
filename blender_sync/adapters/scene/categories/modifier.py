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
# Particles are handled separately by ParticleCategoryHandler.
_NESTED_SETTINGS_ATTRS = (
    "settings",            # Cloth, SoftBody
    "collision_settings",  # Cloth
    "domain_settings",     # Fluid (when fluid_type == 'DOMAIN')
    "flow_settings",       # Fluid (when fluid_type == 'FLOW')
    "effector_settings",   # Fluid (when fluid_type == 'EFFECTOR')
    "point_cache",         # Cloth/SoftBody — playback range only, not bake data
)

# Sub-structs reached one level under _NESTED_SETTINGS_ATTRS. Most
# physics settings hide effector weighting (gravity, wind, vortex...)
# here; without descending peers won't reproduce force-field response
# and sims will still drift even after the parent struct sync.
_DEEP_NESTED_ATTRS = (
    "effector_weights",
)

_NESTED_PROP_BLACKLIST = {
    "rna_type", "bl_rna",
    # Skip baked / cached data — far too large for the wire and not
    # reproducible across machines anyway. Peers re-bake locally.
    "data", "data_types", "info",
    # PointCache read-only flags. Sending them just produces silent
    # setattr failures on the receiver.
    "is_baked", "is_baking", "is_outdated", "is_frame_skip",
    # Collections of cache items, not directly settable.
    "point_caches",
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
        # GeometryNodes modifier instance ID-props.
        # Each socket on the bound NodeTree exposes:
        #   mod["Input_<N>"]                    — current value
        #   mod["Input_<N>_attribute_name"]     — attribute override
        #   mod["Input_<N>_use_attribute"]      — bool toggle
        # `dir(mod)` does not enumerate ID-props, so the previous walker
        # missed them entirely and peers using Geometry Nodes saw all
        # inputs reset to the tree defaults. Pull them via .keys().
        if mod.type == "NODES":
            id_props: dict[str, Any] = {}
            try:
                keys = list(mod.keys())
            except Exception:
                keys = []
            for key in keys:
                if not isinstance(key, str) or key.startswith("_"):
                    continue
                try:
                    val = mod[key]
                except Exception:
                    continue
                serialized = (
                    val if isinstance(val, _PRIM) else _serialize_value(val)
                )
                if serialized is not None:
                    id_props[key] = serialized
            if id_props:
                out["id_props"] = id_props

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
        """Serialize a single Blender RNA sub-struct.

        Used for ClothSettings, SoftBodySettings, FluidDomainSettings,
        etc. — anywhere a physics modifier hides its real state.
        Recurses one extra level into specifically-named sub-structs
        (currently `effector_weights`) so force-field response stays in
        sync between peers.
        """
        out: dict[str, Any] = {}
        deep: dict[str, dict[str, Any]] = {}
        for attr in dir(struct):
            if attr.startswith("_") or attr in _NESTED_PROP_BLACKLIST:
                continue
            try:
                val = getattr(struct, attr)
            except Exception:
                continue
            if callable(val):
                continue
            if attr in _DEEP_NESTED_ATTRS and val is not None:
                inner = self._serialize_leaf_struct(val)
                if inner:
                    deep[attr] = inner
                continue
            serialized = (
                val if isinstance(val, _PRIM) else _serialize_value(val)
            )
            if serialized is not None:
                out[attr] = serialized
        if deep:
            out["__deep__"] = deep
        return out

    def _serialize_leaf_struct(self, struct) -> dict[str, Any]:
        """Final-level walk; only primitives. Used for sub-sub-structs
        like EffectorWeights where we don't want any further recursion."""
        out: dict[str, Any] = {}
        for attr in dir(struct):
            if attr.startswith("_") or attr in _NESTED_PROP_BLACKLIST:
                continue
            try:
                val = getattr(struct, attr)
            except Exception:
                continue
            if callable(val) or not isinstance(val, _PRIM):
                continue
            out[attr] = val
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

            # GeometryNodes ID-props (Input_*, Input_*_attribute_name, ...).
            for key, val in (entry.get("id_props") or {}).items():
                try:
                    new_mod[key] = val
                except Exception:
                    continue

    def _apply_struct(self, struct, inner: dict) -> None:
        deep = inner.get("__deep__")
        for k, v in inner.items():
            if k == "__deep__":
                continue
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
        if deep:
            for sub_attr, sub_props in deep.items():
                sub = getattr(struct, sub_attr, None)
                if sub is None:
                    continue
                for k, v in sub_props.items():
                    if not hasattr(sub, k):
                        continue
                    try:
                        setattr(sub, k, v)
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

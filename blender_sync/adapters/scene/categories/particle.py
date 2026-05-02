"""Particle System handler.

Synchronizes Object.particle_systems and the bpy.data.particles settings
they reference. Baked simulation cache is intentionally out of scope —
particle physics is stochastic and reseed will replay deterministically
on the receiver if seed and settings match.

Children (interpolated/simple), hair dynamics (`use_hair_dynamics` +
hair-dynamics ClothSettings), and effector weights are all carried over
the wire — without them peers see the wrong child count, wrong drape,
or different gravity response on hair.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
from .base import DirtyContext

_PRIM = (int, float, bool, str)

# Properties handled out-of-band (datablock refs, deep structs) or
# simply not safe to round-trip through the generic walker.
_PSETTINGS_BLACKLIST = {
    "rna_type", "bl_rna", "name",
    "active_instance_object", "active_texture", "active_texture_index",
    # Datablock-typed: handled separately via _DATABLOCK_REF_FIELDS so
    # the wire encoding survives msgpack and gets re-resolved on apply.
    "instance_collection", "instance_object",
    "collision_collection",
    "texture_slots",
    # Deep struct: handled separately via _DEEP_NESTED_FIELDS.
    # `force_field_1` / `force_field_2` are FieldSettings sub-structs
    # (always non-None, not datablock pointers) — they belong here, not
    # in the ref list.
    "boids", "fluid", "effector_weights",
    "force_field_1", "force_field_2",
}

# ParticleSettings fields whose value is a bpy datablock. Encoded as a
# `__bsync_ref__:<kind>:<name>` sentinel and re-resolved on the receiver.
_DATABLOCK_REF_FIELDS = (
    "instance_object",
    "instance_collection",
    "collision_collection",
)

# Sub-structs reached one level under ParticleSettings. `force_field_1`
# / `force_field_2` are auto-allocated FieldSettings — never None — and
# carry per-particle force settings (type, strength, falloff, ...).
# Without descending into them, peers see the wrong field type on hair
# / particle physics.
_DEEP_NESTED_FIELDS = (
    "effector_weights",
    "force_field_1",
    "force_field_2",
)

_DEEP_BLACKLIST = {"rna_type", "bl_rna"}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, _PRIM):
        return value
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


def _serialize_leaf_struct(struct) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in dir(struct):
        if attr.startswith("_") or attr in _DEEP_BLACKLIST:
            continue
        try:
            val = getattr(struct, attr)
        except Exception:
            continue
        if callable(val) or not isinstance(val, _PRIM):
            continue
        out[attr] = val
    return out


def _serialize_settings(ps) -> dict[str, Any]:
    out: dict[str, Any] = {"name": ps.name, "props": {}}
    for attr in dir(ps):
        if attr.startswith("_") or attr in _PSETTINGS_BLACKLIST:
            continue
        try:
            val = getattr(ps, attr)
        except Exception:
            continue
        if callable(val):
            continue
        ser = _serialize_value(val)
        if ser is not None:
            out["props"][attr] = ser

    # Datablock-typed pointer fields — encoded as sentinels.
    refs: dict[str, str] = {}
    for fld in _DATABLOCK_REF_FIELDS:
        if not hasattr(ps, fld):
            continue
        try:
            v = getattr(ps, fld)
        except Exception:
            continue
        if v is None:
            # Empty string acts as an explicit "clear" so peers can
            # mirror unsetting a reference.
            refs[fld] = ""
            continue
        ref = _datablock_ref.try_ref(v)
        if ref is not None:
            refs[fld] = ref
    if refs:
        out["refs"] = refs

    # Deep walk into structs that hide critical state (effector weights:
    # gravity / wind / vortex / turbulence ...).
    deep: dict[str, dict[str, Any]] = {}
    for fld in _DEEP_NESTED_FIELDS:
        if not hasattr(ps, fld):
            continue
        try:
            sub = getattr(ps, fld)
        except Exception:
            continue
        if sub is None:
            continue
        inner = _serialize_leaf_struct(sub)
        if inner:
            deep[fld] = inner
    if deep:
        out["deep"] = deep
    return out


class ParticleCategoryHandler:
    category_name = "particle"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for owner_name in list(ctx.particles):
            obj = bpy.data.objects.get(owner_name)
            if obj is None or not hasattr(obj, "particle_systems"):
                continue
            entry = self._serialize_object(obj)
            if entry is not None:
                ops.append(entry)
        return ops

    def _serialize_object(self, obj) -> dict[str, Any] | None:
        # Capability check: only objects that *can* hold particle
        # systems are valid here. Returning an empty `systems` list is
        # a meaningful op — apply interprets it as "remove all
        # particle systems" — which is required for undo cases where
        # the user just removed the last system on the object.
        if not hasattr(obj, "particle_systems"):
            return None
        systems = []
        for psys in obj.particle_systems:
            settings = psys.settings
            systems.append({
                "name": psys.name,
                "settings": _serialize_settings(settings) if settings else None,
                "seed": int(getattr(psys, "seed", 0)),
                "vertex_group_density": str(getattr(psys, "vertex_group_density", "")),
                "vertex_group_length": str(getattr(psys, "vertex_group_length", "")),
            })
        return {"obj": obj.name, "systems": systems}

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or not hasattr(obj, "particle_systems"):
                continue
            self._apply_systems(bpy, obj, op.get("systems") or [])

    def _apply_systems(self, bpy, obj, systems: list[dict]) -> None:
        target_n = len(systems)
        cur_n = len(obj.particle_systems)

        # Removing happens last-in-first-out (reversed) so existing
        # system indices remain stable for the prop-update loop below.
        while cur_n > target_n:
            removed = False
            for m in reversed(list(obj.modifiers)):
                if getattr(m, "type", "") == "PARTICLE_SYSTEM":
                    try:
                        obj.modifiers.remove(m)
                        removed = True
                        cur_n -= 1
                        break
                    except Exception:
                        pass
            if not removed:
                break

        # When adding, use the wire-supplied name where possible. Blender
        # auto-suffixes on collision; we accept that since system index
        # is what matters for prop-application.
        for i in range(cur_n, target_n):
            requested = systems[i].get("name") or f"ParticleSystem.{i + 1}"
            try:
                mod = obj.modifiers.new(
                    name=requested,
                    type="PARTICLE_SYSTEM",
                )
                if mod is None:
                    break
            except Exception:
                break
            cur_n += 1

        n = min(cur_n, target_n)
        for i in range(n):
            psys = obj.particle_systems[i]
            sd = systems[i]
            try:
                psys.name = sd.get("name", psys.name)
            except Exception:
                pass
            for k in ("vertex_group_density", "vertex_group_length"):
                if k in sd:
                    try:
                        setattr(psys, k, sd[k])
                    except Exception:
                        pass
            if "seed" in sd:
                try:
                    psys.seed = int(sd["seed"])
                except Exception:
                    pass
            settings_data = sd.get("settings") or {}
            if psys.settings is not None and settings_data:
                pset = psys.settings
                for k, v in (settings_data.get("props") or {}).items():
                    if hasattr(pset, k):
                        try:
                            setattr(pset, k, v)
                        except Exception:
                            pass
                # Datablock-typed pointer fields.
                for k, token in (settings_data.get("refs") or {}).items():
                    if not hasattr(pset, k):
                        continue
                    if token == "":
                        try:
                            setattr(pset, k, None)
                        except Exception:
                            pass
                        continue
                    resolved = _datablock_ref.resolve_ref(token)
                    if resolved is None:
                        continue
                    try:
                        setattr(pset, k, resolved)
                    except Exception:
                        pass
                # Deep structs (effector_weights ...).
                for sub_attr, sub_props in (settings_data.get("deep") or {}).items():
                    sub = getattr(pset, sub_attr, None)
                    if sub is None:
                        continue
                    for k, v in sub_props.items():
                        if not hasattr(sub, k):
                            continue
                        try:
                            setattr(sub, k, v)
                        except Exception:
                            pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            if not hasattr(obj, "particle_systems"):
                continue
            entry = self._serialize_object(obj)
            if entry is not None:
                out.append(entry)
        return out

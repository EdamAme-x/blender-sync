"""Particle System handler.

Synchronizes Object.particle_systems and the bpy.data.particles settings
they reference. Baked simulation cache is intentionally out of scope —
particle physics is stochastic and reseed will replay deterministically
on the receiver if seed and settings match.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext

_PRIM = (int, float, bool, str)

_PSETTINGS_BLACKLIST = {
    "rna_type", "bl_rna", "name",
    "active_instance_object", "active_texture",
    "force_field_1", "force_field_2",
    "instance_collection", "instance_object",
    "render_step", "draw_step",
    "boids", "fluid", "effector_weights",
    "render_type",
}


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
        if not obj.particle_systems:
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
                for k, v in (settings_data.get("props") or {}).items():
                    if hasattr(psys.settings, k):
                        try:
                            setattr(psys.settings, k, v)
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

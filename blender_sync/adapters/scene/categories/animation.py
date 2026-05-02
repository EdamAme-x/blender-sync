"""Animation handler.

Synchronizes Object.animation_data:
  - The bound Action name
  - All FCurves (data_path, array_index, keyframe_points)

Drivers and NLA strips are out of scope for this initial version. Action
data blocks themselves are also serialized when first encountered, so
joining peers can replay keyframes without the host having to broadcast
the same Action repeatedly.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


def _serialize_keyframe(kp) -> dict[str, Any]:
    co = list(kp.co)
    return {
        "co": [float(co[0]), float(co[1])],
        "interp": getattr(kp, "interpolation", "BEZIER"),
        "left": list(kp.handle_left) if hasattr(kp, "handle_left") else None,
        "right": list(kp.handle_right) if hasattr(kp, "handle_right") else None,
    }


def _serialize_fcurve(fc) -> dict[str, Any]:
    return {
        "data_path": fc.data_path,
        "array_index": int(fc.array_index),
        "keyframes": [_serialize_keyframe(kp) for kp in fc.keyframe_points],
    }


def _serialize_action(action) -> dict[str, Any]:
    return {
        "name": action.name,
        "fcurves": [_serialize_fcurve(fc) for fc in action.fcurves],
        "use_cyclic": bool(getattr(action, "use_cyclic", False)),
    }


def _serialize_driver_var(var) -> dict[str, Any]:
    targets = []
    for tgt in var.targets:
        td = {
            "data_path": getattr(tgt, "data_path", "") or "",
            "transform_type": getattr(tgt, "transform_type", "LOC_X"),
            "transform_space": getattr(tgt, "transform_space", "WORLD_SPACE"),
        }
        idobj = getattr(tgt, "id", None)
        if idobj is not None and getattr(idobj, "name", None):
            td["id_name"] = idobj.name
            td["id_type"] = getattr(tgt, "id_type", "OBJECT")
        targets.append(td)
    return {
        "name": var.name,
        "type": getattr(var, "type", "SINGLE_PROP"),
        "targets": targets,
    }


def _serialize_driver_fcurve(fc) -> dict[str, Any]:
    drv = fc.driver
    return {
        "data_path": fc.data_path,
        "array_index": int(fc.array_index),
        "expression": getattr(drv, "expression", "") or "",
        "type": getattr(drv, "type", "SCRIPTED"),
        "variables": [_serialize_driver_var(v) for v in drv.variables],
    }


def _serialize_nla_strip(strip) -> dict[str, Any]:
    return {
        "name": strip.name,
        "frame_start": float(strip.frame_start),
        "frame_end": float(strip.frame_end),
        "action": strip.action.name if strip.action else None,
        "blend_type": getattr(strip, "blend_type", "REPLACE"),
        "extrapolation": getattr(strip, "extrapolation", "HOLD"),
        "influence": float(getattr(strip, "influence", 1.0)),
        "use_animated_influence": bool(getattr(strip, "use_animated_influence", False)),
        "mute": bool(getattr(strip, "mute", False)),
    }


def _serialize_nla_track(track) -> dict[str, Any]:
    return {
        "name": track.name,
        "mute": bool(getattr(track, "mute", False)),
        "is_solo": bool(getattr(track, "is_solo", False)),
        "strips": [_serialize_nla_strip(s) for s in track.strips],
    }


_OWNER_LOOKUP = (
    ("object",   "objects"),
    ("material", "materials"),
    ("world",    "worlds"),
    ("camera",   "cameras"),
    ("light",    "lights"),
    ("armature", "armatures"),
)


def _resolve_owner(bpy, owner_type: str, name: str):
    for kind, attr in _OWNER_LOOKUP:
        if kind == owner_type:
            coll = getattr(bpy.data, attr, None)
            return coll.get(name) if coll is not None else None
    return None


class AnimationCategoryHandler:
    category_name = "animation"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for entry_name in list(ctx.animations):
            owner_type, name = self._split_owner_key(entry_name)
            owner = _resolve_owner(bpy, owner_type, name)
            if owner is None:
                continue
            entry = self._serialize_owner(owner, owner_type)
            if entry is not None:
                ops.append(entry)
        return ops

    @staticmethod
    def _split_owner_key(key: str) -> tuple[str, str]:
        # ctx.animations entries are stored as "<owner_type>:<name>".
        # Legacy entries (just the object name) fall back to "object".
        kind, sep, name = key.partition(":")
        if not sep:
            return "object", kind
        return kind, name

    def _serialize_owner(self, owner, owner_type: str = "object") -> dict[str, Any] | None:
        ad = getattr(owner, "animation_data", None)
        if ad is None:
            # animation_data was cleared entirely (rare — typically
            # via animation_data_clear() or undo of "make local").
            # Emit a clear-op so peers drop their stale Action /
            # drivers / NLA tracks. Apply path interprets the empty
            # action/drivers/nla_tracks as "remove all".
            return {
                "owner": owner.name,
                "owner_type": owner_type,
                "clear": True,
            }
        out: dict[str, Any] = {
            "owner": owner.name,
            "owner_type": owner_type,
        }
        if ad.action is not None:
            out["action"] = _serialize_action(ad.action)

        drivers = list(getattr(ad, "drivers", []) or [])
        if drivers:
            out["drivers"] = [_serialize_driver_fcurve(fc) for fc in drivers]

        tracks = list(getattr(ad, "nla_tracks", []) or [])
        if tracks:
            out["nla_tracks"] = [_serialize_nla_track(t) for t in tracks]

        # Even when action / drivers / nla_tracks are all empty (e.g.
        # the user just removed the last driver via undo), still emit
        # the op so peers clear their stale state. The apply path
        # treats missing keys as "no change in that sub-area" but
        # honors empty arrays / None action explicitly.
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            owner_name = op.get("owner", "")
            owner_type = op.get("owner_type", "object")
            owner = _resolve_owner(bpy, owner_type, owner_name)
            if owner is None:
                continue
            if op.get("clear"):
                # Sender's animation_data was cleared entirely. Peer
                # mirrors that — drop the whole animation_data block.
                try:
                    if owner.animation_data is not None:
                        owner.animation_data_clear()
                except Exception:
                    pass
                continue
            if "action" in op:
                self._apply_action(bpy, owner, op.get("action", {}))
            if "drivers" in op:
                self._apply_drivers(bpy, owner, op.get("drivers") or [])
            if "nla_tracks" in op:
                self._apply_nla(bpy, owner, op.get("nla_tracks") or [])

    @staticmethod
    def _datablock_for_id_type(bpy, id_type: str):
        # Driver target id_type names map to bpy.data.* collections.
        mapping = {
            "OBJECT": bpy.data.objects,
            "MESH": bpy.data.meshes,
            "MATERIAL": bpy.data.materials,
            "LIGHT": getattr(bpy.data, "lights", None),
            "CAMERA": bpy.data.cameras,
            "ARMATURE": bpy.data.armatures,
            "WORLD": bpy.data.worlds,
            "SCENE": bpy.data.scenes,
            "TEXTURE": bpy.data.textures,
            "IMAGE": bpy.data.images,
            "ACTION": bpy.data.actions,
            "NODETREE": bpy.data.node_groups,
            "PARTICLE": getattr(bpy.data, "particles", None),
            "CURVE": bpy.data.curves,
            "LATTICE": bpy.data.lattices,
            "METABALL": bpy.data.metaballs,
            "COLLECTION": bpy.data.collections,
        }
        return mapping.get(id_type)

    def _apply_drivers(self, bpy, owner, drivers: list[dict]) -> None:
        if owner.animation_data is None:
            try:
                owner.animation_data_create()
            except Exception:
                return
        ad = owner.animation_data
        # Remove existing drivers; re-create from incoming list.
        try:
            for fc in list(ad.drivers):
                try:
                    owner.driver_remove(fc.data_path, fc.array_index)
                except Exception:
                    try:
                        ad.drivers.remove(fc)
                    except Exception:
                        pass
        except Exception:
            pass
        for d in drivers:
            data_path = d.get("data_path")
            if not data_path:
                continue
            try:
                fc = owner.driver_add(data_path, int(d.get("array_index", 0)))
            except Exception:
                continue
            drv = fc.driver
            try:
                drv.expression = d.get("expression", "") or ""
                drv.type = d.get("type", "SCRIPTED")
            except Exception:
                pass
            for vd in d.get("variables", []):
                try:
                    var = drv.variables.new()
                    var.name = vd.get("name", var.name)
                    var.type = vd.get("type", "SINGLE_PROP")
                except Exception:
                    continue
                for i, td in enumerate(vd.get("targets", [])):
                    if i >= len(var.targets):
                        break
                    tgt = var.targets[i]
                    id_type = td.get("id_type", "OBJECT")
                    id_name = td.get("id_name")
                    if id_name:
                        coll = self._datablock_for_id_type(bpy, id_type)
                        idobj = coll.get(id_name) if coll is not None else None
                        if idobj is not None:
                            if hasattr(tgt, "id_type"):
                                try:
                                    tgt.id_type = id_type
                                except Exception:
                                    pass
                            try:
                                tgt.id = idobj
                            except Exception:
                                pass
                    for k in ("data_path", "transform_type", "transform_space"):
                        if k in td and hasattr(tgt, k):
                            try:
                                setattr(tgt, k, td[k])
                            except Exception:
                                pass

    def _apply_nla(self, bpy, owner, tracks: list[dict]) -> None:
        if owner.animation_data is None:
            try:
                owner.animation_data_create()
            except Exception:
                return
        ad = owner.animation_data
        try:
            for t in list(ad.nla_tracks):
                ad.nla_tracks.remove(t)
        except Exception:
            pass
        for td in tracks:
            try:
                track = ad.nla_tracks.new()
                track.name = td.get("name", track.name)
                track.mute = bool(td.get("mute", False))
                if hasattr(track, "is_solo"):
                    try:
                        track.is_solo = bool(td.get("is_solo", False))
                    except Exception:
                        pass
            except Exception:
                continue
            for sd in td.get("strips", []):
                action_name = sd.get("action")
                action = (
                    bpy.data.actions.get(action_name) if action_name else None
                )
                if action is None:
                    continue
                try:
                    strip = track.strips.new(
                        sd.get("name", "Strip"),
                        int(sd.get("frame_start", 1)),
                        action,
                    )
                    strip.frame_end = float(sd.get("frame_end", strip.frame_end))
                    for k in ("blend_type", "extrapolation"):
                        if k in sd:
                            try:
                                setattr(strip, k, sd[k])
                            except Exception:
                                pass
                    for k in ("influence", "use_animated_influence", "mute"):
                        if k in sd and hasattr(strip, k):
                            try:
                                setattr(strip, k, sd[k])
                            except Exception:
                                pass
                except Exception:
                    pass

    def _apply_action(self, bpy, owner, action_data: dict) -> None:
        action_name = action_data.get("name")
        if not action_name:
            return
        action = bpy.data.actions.get(action_name)
        if action is None:
            try:
                action = bpy.data.actions.new(action_name)
            except Exception:
                return

        # Reset existing fcurves to avoid duplication on repeated apply.
        try:
            for fc in list(action.fcurves):
                action.fcurves.remove(fc)
        except Exception:
            pass

        for fc_data in action_data.get("fcurves", []):
            data_path = fc_data.get("data_path")
            if not data_path:
                continue
            try:
                fc = action.fcurves.new(
                    data_path=data_path,
                    index=int(fc_data.get("array_index", 0)),
                )
            except Exception:
                continue
            for kp_data in fc_data.get("keyframes", []):
                co = kp_data.get("co") or [0, 0]
                if len(co) < 2:
                    continue
                try:
                    kp = fc.keyframe_points.insert(float(co[0]), float(co[1]))
                    interp = kp_data.get("interp")
                    if interp:
                        try:
                            kp.interpolation = interp
                        except Exception:
                            pass
                    left = kp_data.get("left")
                    if left and len(left) == 2:
                        try:
                            kp.handle_left = (float(left[0]), float(left[1]))
                        except Exception:
                            pass
                    right = kp_data.get("right")
                    if right and len(right) == 2:
                        try:
                            kp.handle_right = (float(right[0]), float(right[1]))
                        except Exception:
                            pass
                except Exception:
                    pass

        if owner.animation_data is None:
            try:
                owner.animation_data_create()
            except Exception:
                return
        try:
            owner.animation_data.action = action
        except Exception:
            pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for kind, attr in _OWNER_LOOKUP:
            coll = getattr(bpy.data, attr, None)
            if coll is None:
                continue
            for owner in coll:
                entry = self._serialize_owner(owner, kind)
                if entry is not None:
                    out.append(entry)
        return out

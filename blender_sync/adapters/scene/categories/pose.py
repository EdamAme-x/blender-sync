"""Pose-mode bone transform handler.

For each Object with type=='ARMATURE', we serialize per-bone:
  - location / rotation / scale (pose-space transforms applied to the rest)
  - rotation_mode
  - bone constraints (basic: IK target/chain, COPY_ROTATION/LOCATION)

Pose updates fire frequently during animation playback or live rigging,
so we route them through the FAST channel like Object transforms.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


_BONE_CONSTRAINT_FIELDS = [
    "name", "type", "influence", "mute",
    "target_space", "owner_space",
    "use_offset", "head_tail",
]


class PoseCategoryHandler:
    category_name = "pose"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.poses):
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "ARMATURE" or obj.pose is None:
                continue
            ops.append(self._serialize(obj))
        return ops

    def _serialize(self, obj) -> dict[str, Any]:
        bones: list[dict[str, Any]] = []
        for pb in obj.pose.bones:
            entry: dict[str, Any] = {
                "name": pb.name,
                "loc": list(pb.location),
                "scl": list(pb.scale),
            }
            if pb.rotation_mode == "QUATERNION":
                entry["rot"] = list(pb.rotation_quaternion)
                entry["rot_mode"] = "QUAT"
            elif pb.rotation_mode == "AXIS_ANGLE":
                entry["rot"] = list(pb.rotation_axis_angle)
                entry["rot_mode"] = "AXIS_ANGLE"
            else:
                entry["rot"] = list(pb.rotation_euler)
                entry["rot_mode"] = "EULER"
            # Bone color tag (Blender 4+)
            bcolor = getattr(pb, "color", None)
            if bcolor is not None and hasattr(bcolor, "palette"):
                try:
                    entry["color_palette"] = bcolor.palette
                except Exception:
                    pass

            constraints = []
            for c in pb.constraints:
                cd: dict[str, Any] = {}
                for f in _BONE_CONSTRAINT_FIELDS:
                    if hasattr(c, f):
                        try:
                            v = getattr(c, f)
                            if isinstance(v, (int, float, bool, str)):
                                cd[f] = v
                        except Exception:
                            pass
                # Common reference fields by name
                tgt = getattr(c, "target", None)
                if tgt is not None and getattr(tgt, "name", None):
                    cd["target"] = tgt.name
                if hasattr(c, "subtarget"):
                    try:
                        cd["subtarget"] = str(c.subtarget or "")
                    except Exception:
                        pass
                constraints.append(cd)
            if constraints:
                entry["constraints"] = constraints
            bones.append(entry)
        return {"obj": obj.name, "bones": bones}

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            obj = bpy.data.objects.get(op.get("obj", ""))
            if obj is None or obj.type != "ARMATURE" or obj.pose is None:
                continue
            for bd in op.get("bones", []):
                pb = obj.pose.bones.get(bd.get("name", ""))
                if pb is None:
                    continue
                loc = bd.get("loc")
                if loc and len(loc) == 3:
                    try:
                        pb.location = (float(loc[0]), float(loc[1]), float(loc[2]))
                    except Exception:
                        pass
                scl = bd.get("scl")
                if scl and len(scl) == 3:
                    try:
                        pb.scale = (float(scl[0]), float(scl[1]), float(scl[2]))
                    except Exception:
                        pass
                rot = bd.get("rot")
                rmode = bd.get("rot_mode", "EULER")
                if rot:
                    try:
                        if rmode == "QUAT" and len(rot) == 4:
                            pb.rotation_mode = "QUATERNION"
                            pb.rotation_quaternion = (
                                float(rot[0]), float(rot[1]),
                                float(rot[2]), float(rot[3]),
                            )
                        elif rmode == "AXIS_ANGLE" and len(rot) == 4:
                            pb.rotation_mode = "AXIS_ANGLE"
                            pb.rotation_axis_angle = (
                                float(rot[0]), float(rot[1]),
                                float(rot[2]), float(rot[3]),
                            )
                        elif len(rot) >= 3:
                            if pb.rotation_mode in ("QUATERNION", "AXIS_ANGLE"):
                                pb.rotation_mode = "XYZ"
                            pb.rotation_euler = (
                                float(rot[0]), float(rot[1]), float(rot[2])
                            )
                    except Exception:
                        pass

                palette = bd.get("color_palette")
                if palette is not None:
                    bcolor = getattr(pb, "color", None)
                    if bcolor is not None and hasattr(bcolor, "palette"):
                        try:
                            bcolor.palette = palette
                        except Exception:
                            pass

                self._apply_constraints(bpy, pb, bd.get("constraints") or [])

    def _apply_constraints(self, bpy, pb, constraints: list) -> None:
        # Reset and rebuild — bone constraints are typically few per bone.
        try:
            for c in list(pb.constraints):
                pb.constraints.remove(c)
        except Exception:
            pass
        for cd in constraints:
            ctype = cd.get("type")
            if not ctype:
                continue
            try:
                c = pb.constraints.new(type=ctype)
            except Exception:
                continue
            for k, v in cd.items():
                if k in ("type", "target", "subtarget"):
                    continue
                if hasattr(c, k):
                    try:
                        setattr(c, k, v)
                    except Exception:
                        pass
            tgt_name = cd.get("target")
            if tgt_name:
                tgt = bpy.data.objects.get(tgt_name)
                if tgt is not None:
                    try:
                        c.target = tgt
                    except Exception:
                        pass
            sub = cd.get("subtarget")
            if sub and hasattr(c, "subtarget"):
                try:
                    c.subtarget = sub
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE" and obj.pose is not None:
                out.append(self._serialize(obj))
        return out

"""Pose-mode bone transform handler.

For each Object with type=='ARMATURE', we serialize per-bone:
  - location / rotation / scale (pose-space transforms applied to the rest)
  - rotation_mode
  - bone constraints (basic: IK target/chain, COPY_ROTATION/LOCATION)
  - custom display shape (object reference + scale + override transform
    + wireframe width) — for rigs that use mesh widgets

Pose updates fire frequently during animation playback or live rigging,
so we route them through the FAST channel like Object transforms.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
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

            # Custom shape (mesh widget). Rigs that use control bone
            # widgets need this — without it the receiver renders the
            # default octahedron and the rig looks broken.
            #
            # Encode `None` explicitly as the empty string so peers can
            # apply the clear; otherwise a user who unsets a widget would
            # leave peers stuck on the previous shape.
            if hasattr(pb, "custom_shape"):
                cs = pb.custom_shape
                if cs is None:
                    entry["custom_shape"] = ""
                else:
                    ref = _datablock_ref.try_ref(cs)
                    if ref is not None:
                        entry["custom_shape"] = ref
            for k in (
                "custom_shape_scale_xyz", "custom_shape_translation",
                "custom_shape_rotation_euler",
            ):
                v = getattr(pb, k, None)
                if v is not None:
                    try:
                        entry[k] = list(v)
                    except Exception:
                        pass
            for k in (
                "use_custom_shape_bone_size", "custom_shape_wire_width",
            ):
                if hasattr(pb, k):
                    try:
                        v = getattr(pb, k)
                        if isinstance(v, (int, float, bool)):
                            entry[k] = v
                    except Exception:
                        pass
            # custom_shape_transform: an override pose-bone whose space
            # the widget is drawn in. Same null-as-clear convention as
            # custom_shape so peers can unset it.
            if hasattr(pb, "custom_shape_transform"):
                cstrans = pb.custom_shape_transform
                if cstrans is None:
                    entry["custom_shape_transform"] = ""
                else:
                    n = getattr(cstrans, "name", None)
                    if n:
                        entry["custom_shape_transform"] = n

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

                self._apply_custom_shape(bpy, pb, bd, obj)
                self._apply_constraints(bpy, pb, bd.get("constraints") or [])

    def _apply_custom_shape(self, bpy, pb, bd: dict, owner_obj) -> None:
        cs_token = bd.get("custom_shape")
        if cs_token is not None:
            if cs_token == "":
                # Explicit clear.
                try:
                    pb.custom_shape = None
                except Exception:
                    pass
            else:
                target = _datablock_ref.resolve_ref(cs_token)
                if target is not None:
                    try:
                        pb.custom_shape = target
                    except Exception:
                        pass
                # If unresolved, the bone keeps its previous shape; the
                # next snapshot tick will retry once the referent arrives.
        for k in (
            "custom_shape_scale_xyz", "custom_shape_translation",
            "custom_shape_rotation_euler",
        ):
            v = bd.get(k)
            if v is None or not hasattr(pb, k):
                continue
            try:
                if len(v) == 3:
                    setattr(pb, k, (float(v[0]), float(v[1]), float(v[2])))
            except Exception:
                pass
        for k in ("use_custom_shape_bone_size", "custom_shape_wire_width"):
            if k in bd and hasattr(pb, k):
                try:
                    cur = getattr(pb, k)
                    if isinstance(cur, bool):
                        setattr(pb, k, bool(bd[k]))
                    else:
                        setattr(pb, k, type(cur)(bd[k]))
                except Exception:
                    pass
        cstrans_name = bd.get("custom_shape_transform")
        if cstrans_name is not None and hasattr(pb, "custom_shape_transform"):
            if not cstrans_name:
                try:
                    pb.custom_shape_transform = None
                except Exception:
                    pass
            else:
                # Must be a pose-bone of the same armature.
                target_pb = (
                    owner_obj.pose.bones.get(cstrans_name)
                    if owner_obj.pose else None
                )
                if target_pb is not None:
                    try:
                        pb.custom_shape_transform = target_pb
                    except Exception:
                        pass

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

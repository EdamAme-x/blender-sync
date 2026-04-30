from __future__ import annotations

from typing import Any

from . import _id_props


class TransformCategoryHandler:
    category_name = "transform"

    def collect_dirty(self, dirty_object_names: set) -> list[dict[str, Any]]:
        return self._collect(dirty_object_names)

    def collect(self, ctx) -> list[dict[str, Any]]:
        return self._collect(ctx.objects_transform)

    def _collect(self, names) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(names):
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            ops.append(self._serialize(obj))
        return ops

    def _serialize(self, obj) -> dict[str, Any]:
        if obj.rotation_mode == "QUATERNION":
            rot = list(obj.rotation_quaternion)
            rot_mode = "QUAT"
        elif obj.rotation_mode == "AXIS_ANGLE":
            rot = list(obj.rotation_axis_angle)
            rot_mode = "AXIS_ANGLE"
        else:
            rot = list(obj.rotation_euler)
            rot_mode = "EULER"
        out: dict[str, Any] = {
            "n": obj.name,
            "loc": list(obj.location),
            "rot": rot,
            "rot_mode": rot_mode,
            "scl": list(obj.scale),
        }

        # Delta transforms (used by parent/animation systems).
        try:
            out["dloc"] = list(obj.delta_location)
            out["dscl"] = list(obj.delta_scale)
            if obj.rotation_mode == "QUATERNION":
                out["drot"] = list(obj.delta_rotation_quaternion)
            else:
                out["drot"] = list(obj.delta_rotation_euler)
        except Exception:
            pass

        # Object-level viewport overlay color.
        try:
            out["color"] = list(obj.color)
        except Exception:
            pass

        # Track axes (used by Track-To/Damped Track constraints).
        for k in ("track_axis", "up_axis"):
            if hasattr(obj, k):
                try:
                    val = getattr(obj, k)
                    if isinstance(val, str):
                        out[k] = val
                except Exception:
                    pass

        # Empty-specific display props.
        if obj.type == "EMPTY":
            for k in ("empty_display_type", "empty_display_size",
                      "empty_image_side"):
                if hasattr(obj, k):
                    try:
                        val = getattr(obj, k)
                        if isinstance(val, (int, float, bool, str)):
                            out[k] = val
                    except Exception:
                        pass
            if hasattr(obj, "empty_image_offset"):
                try:
                    out["empty_image_offset"] = list(obj.empty_image_offset)
                except Exception:
                    pass

        # Parent / hierarchy. Stored by name; receiver resolves on apply.
        parent = getattr(obj, "parent", None)
        if parent is not None and getattr(parent, "name", None):
            out["parent"] = parent.name
            out["parent_type"] = obj.parent_type
            if obj.parent_type == "BONE" and obj.parent_bone:
                out["parent_bone"] = obj.parent_bone
            try:
                # 4x4 matrix as a flat list of 16 floats (row-major).
                m = obj.matrix_parent_inverse
                out["parent_inv"] = [float(c) for row in m for c in row]
            except Exception:
                pass

        # Lock flags — minor but useful for rigs.
        try:
            out["lock_loc"] = list(obj.lock_location)
            out["lock_rot"] = list(obj.lock_rotation)
            out["lock_scl"] = list(obj.lock_scale)
        except Exception:
            pass

        id_props = _id_props.serialize_id_props(obj)
        if id_props:
            out["id_props"] = id_props
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            name = op.get("n")
            if not name:
                continue
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            loc = op.get("loc")
            if loc and len(loc) == 3:
                obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
            scl = op.get("scl")
            if scl and len(scl) == 3:
                obj.scale = (float(scl[0]), float(scl[1]), float(scl[2]))
            rot = op.get("rot")
            mode = op.get("rot_mode", "EULER")
            if rot:
                if mode == "QUAT" and len(rot) == 4:
                    obj.rotation_mode = "QUATERNION"
                    obj.rotation_quaternion = (
                        float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])
                    )
                elif mode == "AXIS_ANGLE" and len(rot) == 4:
                    obj.rotation_mode = "AXIS_ANGLE"
                    obj.rotation_axis_angle = (
                        float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])
                    )
                elif len(rot) >= 3:
                    if obj.rotation_mode in ("QUATERNION", "AXIS_ANGLE"):
                        obj.rotation_mode = "XYZ"
                    obj.rotation_euler = (
                        float(rot[0]), float(rot[1]), float(rot[2])
                    )

            # Delta transforms.
            dloc = op.get("dloc")
            if dloc and len(dloc) == 3:
                try:
                    obj.delta_location = (float(dloc[0]), float(dloc[1]), float(dloc[2]))
                except Exception:
                    pass
            dscl = op.get("dscl")
            if dscl and len(dscl) == 3:
                try:
                    obj.delta_scale = (float(dscl[0]), float(dscl[1]), float(dscl[2]))
                except Exception:
                    pass
            drot = op.get("drot")
            if drot:
                try:
                    if len(drot) == 4:
                        obj.delta_rotation_quaternion = tuple(float(v) for v in drot)
                    else:
                        obj.delta_rotation_euler = (
                            float(drot[0]), float(drot[1]), float(drot[2])
                        )
                except Exception:
                    pass

            color = op.get("color")
            if color and len(color) >= 3:
                try:
                    obj.color = tuple(float(c) for c in color[:4])
                except Exception:
                    pass

            for k in ("track_axis", "up_axis",
                      "empty_display_type", "empty_image_side"):
                if k in op and hasattr(obj, k):
                    try:
                        setattr(obj, k, op[k])
                    except Exception:
                        pass
            if "empty_display_size" in op and hasattr(obj, "empty_display_size"):
                try:
                    obj.empty_display_size = float(op["empty_display_size"])
                except Exception:
                    pass
            ofs = op.get("empty_image_offset")
            if ofs and hasattr(obj, "empty_image_offset"):
                try:
                    obj.empty_image_offset = tuple(float(v) for v in ofs)
                except Exception:
                    pass

            self._apply_parent(bpy, obj, op)

            for key, attr in (
                ("lock_loc", "lock_location"),
                ("lock_rot", "lock_rotation"),
                ("lock_scl", "lock_scale"),
            ):
                vals = op.get(key)
                if vals and hasattr(obj, attr):
                    try:
                        setattr(obj, attr, tuple(bool(v) for v in vals))
                    except Exception:
                        pass

            id_props = op.get("id_props")
            if id_props:
                _id_props.apply_id_props(obj, id_props)

    def _apply_parent(self, bpy, obj, op: dict) -> None:
        parent_name = op.get("parent")
        if parent_name is None:
            if obj.parent is not None:
                try:
                    obj.parent = None
                except Exception:
                    pass
            return
        parent = bpy.data.objects.get(parent_name)
        if parent is None:
            # Parent not yet synced. Skip — the next transform op will
            # resolve once the parent arrives.
            return
        try:
            obj.parent = parent
            ptype = op.get("parent_type")
            if ptype:
                obj.parent_type = ptype
            if ptype == "BONE":
                bone = op.get("parent_bone")
                if bone:
                    obj.parent_bone = bone
            inv = op.get("parent_inv")
            if inv and len(inv) == 16:
                from mathutils import Matrix  # type: ignore
                obj.matrix_parent_inverse = Matrix((
                    inv[0:4], inv[4:8], inv[8:12], inv[12:16],
                ))
        except Exception:
            pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(o) for o in bpy.data.objects]

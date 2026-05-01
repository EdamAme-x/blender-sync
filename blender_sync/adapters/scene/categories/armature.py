"""Armature data block handler.

Synchronizes the rest pose: bone hierarchy (head/tail/roll/parent) plus
edit-mode-only properties. Pose-mode bone transforms (live animation
edits) are handled by PoseCategoryHandler.

Armature edits require entering Edit Mode in Blender, which is rare
during a session — we send the full bone list whenever the armature
data block is dirty.
"""
from __future__ import annotations

from typing import Any

from . import _id_props
from .base import DirtyContext


class ArmatureCategoryHandler:
    category_name = "armature"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.armatures):
            arm = bpy.data.armatures.get(name)
            if arm is None:
                continue
            ops.append(self._serialize(arm))
        return ops

    def _serialize(self, arm) -> dict[str, Any]:
        bones: list[dict[str, Any]] = []
        for b in arm.bones:
            bd = {
                "name": b.name,
                "head": list(b.head_local),
                "tail": list(b.tail_local),
                "roll": float(getattr(b, "roll", 0.0)),
                "parent": b.parent.name if b.parent else None,
                "use_connect": bool(getattr(b, "use_connect", False)),
                "use_deform": bool(getattr(b, "use_deform", True)),
                "use_inherit_rotation": bool(getattr(b, "use_inherit_rotation", True)),
                "envelope_distance": float(getattr(b, "envelope_distance", 0.25)),
                "envelope_weight": float(getattr(b, "envelope_weight", 1.0)),
            }
            # B-Bone segments (Blender 2.8+)
            for k in ("bbone_segments", "bbone_x", "bbone_z",
                      "bbone_easein", "bbone_easeout",
                      "bbone_handle_type_start", "bbone_handle_type_end"):
                if hasattr(b, k):
                    try:
                        v = getattr(b, k)
                        if isinstance(v, (int, float, bool, str)):
                            bd[k] = v
                    except Exception:
                        pass
            # Bone collections (Blender 4+) — list of names this bone belongs to
            collections = getattr(b, "collections", None)
            if collections is not None:
                try:
                    bd["collections"] = [c.name for c in collections]
                except Exception:
                    pass
            bones.append(bd)

        out: dict[str, Any] = {
            "name": arm.name,
            "bones": bones,
            "display_type": getattr(arm, "display_type", "OCTAHEDRAL"),
            "show_axes": bool(getattr(arm, "show_axes", False)),
            "show_names": bool(getattr(arm, "show_names", False)),
        }
        ip = _id_props.serialize_id_props(arm)
        if ip:
            out["id_props"] = ip

        # Bone collections (top-level, Blender 4+).
        bcs = getattr(arm, "collections", None)
        if bcs is not None:
            try:
                # In 4.1+ this is `collections_all` for nested ones.
                source = getattr(arm, "collections_all", None) or arm.collections
                out["bone_collections"] = [
                    {"name": c.name, "is_visible": bool(getattr(c, "is_visible", True))}
                    for c in source
                ]
            except Exception:
                pass

        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        # Editing armature bones requires bpy.ops.object.mode_set('EDIT'),
        # which we cannot safely call from within depsgraph callbacks.
        # We defer this to a context-aware helper — for now, log and skip.
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            arm = bpy.data.armatures.get(op.get("name", ""))
            if arm is None:
                try:
                    arm = bpy.data.armatures.new(name=op["name"])
                except Exception:
                    continue
            for k in ("display_type",):
                if k in op and hasattr(arm, k):
                    try:
                        setattr(arm, k, op[k])
                    except Exception:
                        pass
            for k in ("show_axes", "show_names"):
                if k in op and hasattr(arm, k):
                    try:
                        setattr(arm, k, bool(op[k]))
                    except Exception:
                        pass
            # Bone collections (4+): create before bones reference them.
            bcs = op.get("bone_collections") or []
            if bcs and hasattr(arm, "collections"):
                existing = {c.name for c in arm.collections}
                for entry in bcs:
                    name = entry.get("name", "")
                    if not name or name in existing:
                        continue
                    try:
                        arm.collections.new(name=name)
                    except Exception:
                        pass
                for entry in bcs:
                    coll = arm.collections.get(entry.get("name", ""))
                    if coll is None:
                        continue
                    if "is_visible" in entry and hasattr(coll, "is_visible"):
                        try:
                            coll.is_visible = bool(entry["is_visible"])
                        except Exception:
                            pass

            self._apply_bones(bpy, arm, op.get("bones", []))
            _id_props.apply_id_props(arm, op.get("id_props") or {})

    def _apply_bones(self, bpy, arm, bones_data: list[dict]) -> None:
        # Find an Object whose data is this armature, so we can switch
        # to edit mode and edit edit_bones.
        owner = None
        for o in bpy.data.objects:
            if o.type == "ARMATURE" and o.data is arm:
                owner = o
                break
        if owner is None:
            return

        # Skip silently in headless / background contexts where bpy.ops
        # cannot be invoked. Background mode is the cheaper check, so it
        # comes first.
        if getattr(bpy.app, "background", False):
            return
        view_layer = getattr(bpy.context, "view_layer", None)
        if view_layer is None or not hasattr(view_layer, "objects"):
            return

        prev_active = view_layer.objects.active
        prev_mode = owner.mode if hasattr(owner, "mode") else "OBJECT"
        try:
            view_layer.objects.active = owner
            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except Exception:
                return

            edit_bones = arm.edit_bones
            target_names = {b["name"] for b in bones_data}
            for eb in list(edit_bones):
                if eb.name not in target_names:
                    edit_bones.remove(eb)

            created: dict[str, Any] = {}
            for b in bones_data:
                eb = edit_bones.get(b["name"]) or edit_bones.new(b["name"])
                eb.head = tuple(b.get("head") or (0, 0, 0))
                eb.tail = tuple(b.get("tail") or (0, 1, 0))
                if "roll" in b:
                    try:
                        eb.roll = float(b["roll"])
                    except Exception:
                        pass
                for k in ("use_connect", "use_deform", "use_inherit_rotation"):
                    if k in b:
                        try:
                            setattr(eb, k, bool(b[k]))
                        except Exception:
                            pass
                for k in ("envelope_distance", "envelope_weight"):
                    if k in b:
                        try:
                            setattr(eb, k, float(b[k]))
                        except Exception:
                            pass
                for k in ("bbone_segments", "bbone_x", "bbone_z",
                          "bbone_easein", "bbone_easeout",
                          "bbone_handle_type_start", "bbone_handle_type_end"):
                    if k in b and hasattr(eb, k):
                        try:
                            setattr(eb, k, b[k])
                        except Exception:
                            pass
                created[b["name"]] = eb

            for b in bones_data:
                parent = b.get("parent")
                if parent and parent in created:
                    try:
                        created[b["name"]].parent = created[parent]
                    except Exception:
                        pass
        finally:
            try:
                bpy.ops.object.mode_set(mode=prev_mode)
            except Exception:
                pass
            try:
                view_layer.objects.active = prev_active
            except Exception:
                pass

        # After leaving edit mode, hook each bone into its collections.
        if hasattr(arm, "collections"):
            for b in bones_data:
                wanted = b.get("collections") or []
                if not wanted:
                    continue
                bone = arm.bones.get(b["name"])
                if bone is None:
                    continue
                for coll_name in wanted:
                    coll = arm.collections.get(coll_name)
                    if coll is None:
                        continue
                    try:
                        coll.assign(bone)
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(a) for a in bpy.data.armatures]

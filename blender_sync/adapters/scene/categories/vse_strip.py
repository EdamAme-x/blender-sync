"""Video Sequence Editor strip handler.

Synchronizes the active scene's VSE timeline:
  - strip frame placement (frame_start, frame_final_*, channel)
  - strip type and source (filepath for IMAGE/MOVIE/SOUND, color for COLOR)
  - blend / mute / lock / opacity
  - speed / volume / pitch / pan for sound and effect strips

VSE in Blender 5 renamed `bpy.types.Sequence` -> `bpy.types.Strip`. Both
exist via aliases for now; we read whatever the running build exposes.

Re-applying tears down the timeline and rebuilds it. The cost is
acceptable because edits are typically infrequent (compared with viewport
transforms) and rebuild guarantees we don't end up with partial state.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import _datablock_ref
from .base import DirtyContext

# Common primitive props that exist on most/all strip types.
_COMMON_PROPS = (
    "name", "type", "channel",
    "frame_start", "frame_final_start", "frame_final_end",
    "frame_offset_start", "frame_offset_end",
    "frame_still_start", "frame_still_end",
    "blend_alpha", "blend_type",
    "mute", "lock", "select",
    "use_proxy", "use_flip_x", "use_flip_y",
    "use_float", "use_reverse_frames",
    "color_tag",
    "speed_factor",
)

# Type-specific props. Walked in addition to the common set.
_TYPE_SPECIFIC = {
    "SOUND": (
        "volume", "pitch", "pan",
        "show_waveform",
    ),
    "MOVIE": (
        "use_deinterlace", "stream_index",
    ),
    "IMAGE": (
        "directory",
    ),
    "COLOR": (),  # color emitted via dedicated branch below.
    "TEXT": (
        "text", "font_size", "wrap_width",
        "use_bold", "use_italic", "use_shadow", "use_box",
        "align_x", "align_y",
        "location", "color",
    ),
    "TRANSFORM": (
        "translate_start_x", "translate_start_y",
        "rotation_start", "scale_start_x", "scale_start_y",
        "use_uniform_scale", "interpolation",
    ),
    "GAUSSIAN_BLUR": (
        "size_x", "size_y",
    ),
}


class VSEStripCategoryHandler:
    category_name = "vse_strip"

    def __init__(self) -> None:
        # Per-scene last-sent hash. Suppresses re-sends when the Scene
        # depsgraph fires for unrelated reasons (frame change, render
        # tweaks) but the timeline content hasn't actually moved.
        self._sent_hash: dict[str, str] = {}

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        if not ctx.vse_strip:
            return []
        try:
            import bpy
        except ImportError:
            return []
        scene = bpy.context.scene
        if scene is None:
            return []
        ops = self._serialize(scene)
        out: list[dict[str, Any]] = []
        for op in ops:
            scene_name = op.get("scene", "")
            digest = self._hash_op(op)
            if self._sent_hash.get(scene_name) == digest:
                continue
            self._sent_hash[scene_name] = digest
            out.append(op)
        return out

    def _hash_op(self, op: dict[str, Any]) -> str:
        try:
            payload = json.dumps(op, sort_keys=True, default=str)
        except Exception:
            payload = repr(op)
        return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()

    def _serialize(self, scene) -> list[dict[str, Any]]:
        se = getattr(scene, "sequence_editor", None)
        if se is None:
            return [{"scene": scene.name, "active": False, "strips": []}]
        out_strips: list[dict[str, Any]] = []
        for s in self._iter_strips(se):
            entry = self._serialize_strip(s)
            if entry is not None:
                out_strips.append(entry)
        return [{
            "scene": scene.name,
            "active": True,
            "show_overlay_frame": bool(getattr(se, "show_overlay_frame", False)),
            "strips": out_strips,
        }]

    def _iter_strips(self, se):
        # Blender 5 exposes both `strips_all` and the legacy
        # `sequences_all`. Prefer the new name when present.
        for attr in ("strips_all", "sequences_all"):
            coll = getattr(se, attr, None)
            if coll is None:
                continue
            try:
                return list(coll)
            except Exception:
                continue
        return []

    def _serialize_strip(self, s) -> dict[str, Any] | None:
        out: dict[str, Any] = {}
        for k in _COMMON_PROPS:
            if not hasattr(s, k):
                continue
            try:
                v = getattr(s, k)
            except Exception:
                continue
            if isinstance(v, (int, float, bool, str)):
                out[k] = v
        # Type-specific props.
        stype = out.get("type", "")
        for k in _TYPE_SPECIFIC.get(stype, ()):
            if not hasattr(s, k):
                continue
            try:
                v = getattr(s, k)
            except Exception:
                continue
            if isinstance(v, (int, float, bool, str)):
                out[k] = v
            elif hasattr(v, "__iter__") and not isinstance(v, str):
                try:
                    out[k] = [float(x) for x in v]
                except Exception:
                    pass
        # COLOR strip's color attr is a Vec3.
        if stype == "COLOR" and hasattr(s, "color"):
            try:
                out["color"] = list(s.color)
            except Exception:
                pass
        # Source paths / referenced datablocks.
        if hasattr(s, "filepath"):
            try:
                fp = s.filepath
                if isinstance(fp, str):
                    out["filepath"] = fp
            except Exception:
                pass
        if hasattr(s, "sound") and getattr(s, "sound", None) is not None:
            try:
                out["sound_path"] = getattr(s.sound, "filepath", "") or ""
                out["sound_name"] = s.sound.name
            except Exception:
                pass
        if hasattr(s, "scene") and getattr(s, "scene", None) is not None:
            ref = _datablock_ref.try_ref(s.scene)
            if ref is not None:
                out["scene_ref"] = ref
        if hasattr(s, "scene_camera") and getattr(s, "scene_camera", None) is not None:
            ref = _datablock_ref.try_ref(s.scene_camera)
            if ref is not None:
                out["scene_camera_ref"] = ref
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            scene = bpy.data.scenes.get(op.get("scene", "")) or bpy.context.scene
            if scene is None:
                continue
            self._apply_scene(bpy, scene, op)

    def _apply_scene(self, bpy, scene, op: dict[str, Any]) -> None:
        active = bool(op.get("active", False))
        if not active:
            # Sender has no sequence editor — clear ours to match.
            try:
                if scene.sequence_editor is not None:
                    scene.sequence_editor_clear()
            except Exception:
                pass
            return
        if scene.sequence_editor is None:
            try:
                scene.sequence_editor_create()
            except Exception:
                return
        se = scene.sequence_editor
        if se is None:
            return
        if "show_overlay_frame" in op and hasattr(se, "show_overlay_frame"):
            try:
                se.show_overlay_frame = bool(op["show_overlay_frame"])
            except Exception:
                pass

        # Tear down existing strips, then rebuild from the wire.
        # `strips` (new) / `sequences` (old) is the *editable* collection
        # versus the *_all flattened views.
        coll = (
            getattr(se, "strips", None)
            or getattr(se, "sequences", None)
        )
        if coll is None:
            return
        try:
            for existing in list(coll):
                coll.remove(existing)
        except Exception:
            pass

        for sd in op.get("strips") or []:
            stype = sd.get("type")
            name = sd.get("name") or "Strip"
            ch = int(sd.get("channel", 1))
            fs = int(sd.get("frame_start", 1))
            new_strip = self._create_strip(coll, stype, name, ch, fs, sd)
            if new_strip is None:
                continue
            self._apply_strip_props(new_strip, sd)

    def _create_strip(self, coll, stype: str, name: str, ch: int, fs: int, sd: dict):
        # Each strip type has its own constructor on the strips/sequences
        # collection. We use the public `new_*` API where possible.
        try:
            if stype == "SOUND":
                fp = sd.get("sound_path") or sd.get("filepath") or ""
                if not fp:
                    return None
                return coll.new_sound(name=name, filepath=fp,
                                      channel=ch, frame_start=fs)
            if stype == "MOVIE":
                fp = sd.get("filepath") or ""
                if not fp:
                    return None
                return coll.new_movie(name=name, filepath=fp,
                                      channel=ch, frame_start=fs)
            if stype == "IMAGE":
                # IMAGE strips need the directory + a frame; for now we
                # let the sender's wire description seed a single-frame
                # placeholder — multi-image strips aren't fully covered.
                directory = sd.get("directory") or ""
                fp = sd.get("filepath") or ""
                if not (directory or fp):
                    return None
                return coll.new_image(name=name, filepath=fp,
                                      channel=ch, frame_start=fs)
            if stype == "COLOR":
                return coll.new_effect(name=name, type="COLOR",
                                       channel=ch,
                                       frame_start=fs,
                                       frame_end=fs + 1)
            if stype in ("TRANSFORM", "GAUSSIAN_BLUR", "ADJUSTMENT",
                          "CROSS", "GAMMA_CROSS", "ADD", "SUBTRACT",
                          "ALPHA_OVER", "ALPHA_UNDER", "MULTIPLY",
                          "OVER_DROP", "WIPE", "GLOW", "SPEED"):
                return coll.new_effect(name=name, type=stype, channel=ch,
                                       frame_start=fs, frame_end=fs + 1)
            if stype == "TEXT":
                return coll.new_effect(name=name, type="TEXT", channel=ch,
                                       frame_start=fs, frame_end=fs + 1)
            if stype == "SCENE":
                # Resolve scene_ref to an actual scene if present.
                token = sd.get("scene_ref")
                target_scene = (
                    _datablock_ref.resolve_ref(token) if token else None
                )
                if target_scene is None:
                    return None
                return coll.new_scene(name=name, scene=target_scene,
                                      channel=ch, frame_start=fs)
        except Exception:
            return None
        return None

    def _apply_strip_props(self, strip, sd: dict) -> None:
        for k, v in sd.items():
            if k in {"name", "type", "channel", "frame_start", "filepath",
                     "directory", "sound_path", "sound_name",
                     "scene_ref", "scene_camera_ref"}:
                continue
            if not hasattr(strip, k):
                continue
            try:
                cur = getattr(strip, k)
                if isinstance(cur, bool):
                    setattr(strip, k, bool(v))
                elif isinstance(cur, (int, float)):
                    setattr(strip, k, type(cur)(v))
                else:
                    setattr(strip, k, v)
            except Exception:
                pass
        cam_token = sd.get("scene_camera_ref")
        if cam_token and hasattr(strip, "scene_camera"):
            cam = _datablock_ref.resolve_ref(cam_token)
            if cam is not None:
                try:
                    strip.scene_camera = cam
                except Exception:
                    pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        scene = bpy.context.scene
        if scene is None:
            return []
        return self._serialize(scene)

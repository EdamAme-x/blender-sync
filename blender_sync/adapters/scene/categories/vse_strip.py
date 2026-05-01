"""Video Sequence Editor strip handler.

Synchronizes the active scene's VSE timeline:
  - strip frame placement (frame_start, channel)
  - strip type and source (filepath for IMAGE/MOVIE/SOUND, color for COLOR)
  - blend / mute / lock / opacity
  - per-strip Transform sub-struct (offset / scale / rotation / filter)
  - speed / volume / pitch / pan for sound and effect strips

Blender 5 renamed `bpy.types.Sequence` -> `bpy.types.Strip` and
`sequence_editor.sequences*` -> `sequence_editor.strips*`. The legacy
names still work in early 5.x as deprecated aliases; we read whichever
the running build exposes.

Apply rebuilds from a clean state (`sequence_editor_clear` +
`sequence_editor_create`) so nothing nested in metas leaks across
syncs. Effect strips that need input1/input2 are created in a second
pass once their inputs exist.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import _datablock_ref
from .base import DirtyContext

# Common primitive props that exist on most/all strip types and are
# safe to round-trip via setattr. Read-only computed fields like
# `frame_final_*` and `frame_still_*` are intentionally absent — they
# derive from `frame_start` + `frame_offset_*` + content length and
# Blender computes them on its own.
_COMMON_PROPS = (
    "name", "type", "channel",
    "frame_start",
    "blend_alpha", "blend_type",
    "mute", "lock", "select",
    "use_proxy", "use_flip_x", "use_flip_y",
    "use_float", "use_reverse_frames",
    "color_tag",
    "speed_factor",
)

# `frame_offset_*` is only writable on strips that have an underlying
# source (movie / sound / image / scene / movieclip / mask / meta).
# Effect strips (color, text, transitions) raise on assignment.
_OFFSET_BEARING_TYPES = {
    "MOVIE", "SOUND", "IMAGE", "SCENE", "MOVIECLIP", "MASK", "META",
}

# Type-specific props. Walked in addition to the common set.
# `TRANSFORM` is intentionally absent — Blender 5 removed the
# transform-effect strip type; the `Strip.transform` sub-struct on
# every strip subsumed it.
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
    "GAUSSIAN_BLUR": (
        "size_x", "size_y",
    ),
}

# Effect types in Blender 5's `new_effect` enum. `TRANSFORM` and
# `OVER_DROP` are gone; `MULTICAM` and `COLORMIX` were retained.
_TWO_INPUT_EFFECTS = {
    "CROSS", "GAMMA_CROSS", "ADD", "SUBTRACT",
    "ALPHA_OVER", "ALPHA_UNDER", "MULTIPLY", "WIPE",
    "COLORMIX",
}
_ONE_INPUT_EFFECTS = {
    "GLOW", "GAUSSIAN_BLUR", "SPEED", "ADJUSTMENT", "MULTICAM",
}
_ZERO_INPUT_EFFECTS = {"COLOR", "TEXT"}

_TRANSFORM_PROPS = (
    "offset_x", "offset_y",
    "scale_x", "scale_y",
    "rotation",
    "origin",   # 2-vec
    "filter",
)


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
        # Prune cache entries for scenes that no longer exist — without
        # this, a deleted-then-recreated scene with the same name would
        # have its first sync silently suppressed.
        live_names = {s.name for s in bpy.data.scenes}
        self._sent_hash = {
            k: v for k, v in self._sent_hash.items() if k in live_names
        }

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
        # Blender 5 uses `strips_all`; older builds use `sequences_all`.
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
        stype = out.get("type", "")

        # frame_offset_* are writable only on source-bearing strips.
        if stype in _OFFSET_BEARING_TYPES:
            for k in ("frame_offset_start", "frame_offset_end"):
                if hasattr(s, k):
                    try:
                        v = getattr(s, k)
                        if isinstance(v, (int, float)):
                            out[k] = v
                    except Exception:
                        pass

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

        if stype == "COLOR" and hasattr(s, "color"):
            try:
                out["color"] = list(s.color)
            except Exception:
                pass

        # Per-strip Transform sub-struct (Blender 5). Encodes offset /
        # scale / rotation / filter that live on `s.transform`.
        tr = getattr(s, "transform", None)
        if tr is not None:
            tr_out: dict[str, Any] = {}
            for k in _TRANSFORM_PROPS:
                if not hasattr(tr, k):
                    continue
                try:
                    v = getattr(tr, k)
                except Exception:
                    continue
                if isinstance(v, (int, float, bool, str)):
                    tr_out[k] = v
                elif hasattr(v, "__iter__") and not isinstance(v, str):
                    try:
                        tr_out[k] = [float(x) for x in v]
                    except Exception:
                        pass
            if tr_out:
                out["transform"] = tr_out

        # Source paths / referenced datablocks.
        if stype in {"MOVIE", "IMAGE"} and hasattr(s, "filepath"):
            try:
                fp = s.filepath
                if isinstance(fp, str):
                    out["filepath"] = fp
            except Exception:
                pass
        if stype == "SOUND" and getattr(s, "sound", None) is not None:
            try:
                out["sound_path"] = getattr(s.sound, "filepath", "") or ""
                out["sound_name"] = s.sound.name
            except Exception:
                pass
        if stype == "SCENE" and getattr(s, "scene", None) is not None:
            ref = _datablock_ref.try_ref(s.scene)
            if ref is not None:
                out["scene_ref"] = ref
        if hasattr(s, "scene_camera") and getattr(s, "scene_camera", None) is not None:
            ref = _datablock_ref.try_ref(s.scene_camera)
            if ref is not None:
                out["scene_camera_ref"] = ref

        # Effect input names — captured by name so we can stitch them
        # back on the receiver during the second pass.
        in1 = getattr(s, "input_1", None)
        if in1 is not None and getattr(in1, "name", None):
            out["input_1"] = in1.name
        in2 = getattr(s, "input_2", None)
        if in2 is not None and getattr(in2, "name", None):
            out["input_2"] = in2.name

        # Wire-supplied `length` lets effect strips reconstruct with
        # the correct duration on the receiver.
        try:
            ff = int(getattr(s, "frame_final_duration", 0))
            if ff > 0:
                out["length"] = ff
        except Exception:
            pass
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
        # Always wipe the existing sequence editor first — otherwise
        # nested meta-strip children would survive into the rebuild and
        # collide with the new ones we're about to create.
        try:
            scene.sequence_editor_clear()
        except Exception:
            pass
        if not active:
            return
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

        coll = (
            getattr(se, "strips", None)
            or getattr(se, "sequences", None)
        )
        if coll is None:
            return

        wire_strips = list(op.get("strips") or [])

        # Pass 1 — create everything that doesn't need other strips as
        # inputs (sources + zero-input effects). Track created ones by
        # the wire-supplied name so pass 2 can resolve input refs.
        created: dict[str, Any] = {}
        deferred: list[dict[str, Any]] = []
        for sd in wire_strips:
            stype = sd.get("type") or ""
            if stype in _ONE_INPUT_EFFECTS or stype in _TWO_INPUT_EFFECTS:
                deferred.append(sd)
                continue
            new_strip = self._create_strip(coll, stype, sd, created)
            if new_strip is not None:
                created[sd.get("name") or new_strip.name] = new_strip
                self._apply_strip_props(new_strip, sd)

        # Pass 2 — effects, now that inputs may exist. We loop until
        # no progress is made to handle chains.
        while deferred:
            progressed = False
            still_pending: list[dict[str, Any]] = []
            for sd in deferred:
                stype = sd.get("type") or ""
                in1_name = sd.get("input_1")
                in2_name = sd.get("input_2") if stype in _TWO_INPUT_EFFECTS else None
                if in1_name and in1_name not in created:
                    still_pending.append(sd)
                    continue
                if (
                    stype in _TWO_INPUT_EFFECTS
                    and in2_name
                    and in2_name not in created
                ):
                    still_pending.append(sd)
                    continue
                new_strip = self._create_strip(coll, stype, sd, created)
                if new_strip is not None:
                    created[sd.get("name") or new_strip.name] = new_strip
                    self._apply_strip_props(new_strip, sd)
                    progressed = True
            if not progressed:
                # Inputs missing; give up on the rest rather than loop.
                break
            deferred = still_pending

    def _create_strip(self, coll, stype: str, sd: dict, created: dict):
        name = sd.get("name") or "Strip"
        ch = int(sd.get("channel", 1))
        fs = int(sd.get("frame_start", 1))
        length = int(sd.get("length", 1)) or 1
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
                fp = sd.get("filepath") or ""
                if not fp:
                    return None
                return coll.new_image(name=name, filepath=fp,
                                      channel=ch, frame_start=fs)
            if stype == "SCENE":
                token = sd.get("scene_ref")
                target_scene = (
                    _datablock_ref.resolve_ref(token) if token else None
                )
                if target_scene is None:
                    return None
                return coll.new_scene(name=name, scene=target_scene,
                                      channel=ch, frame_start=fs)
            if stype in _ZERO_INPUT_EFFECTS:
                return coll.new_effect(name=name, type=stype, channel=ch,
                                       frame_start=fs, length=length)
            if stype in _ONE_INPUT_EFFECTS:
                in1 = created.get(sd.get("input_1") or "")
                if in1 is None:
                    return None
                return coll.new_effect(name=name, type=stype, channel=ch,
                                       frame_start=fs, length=length,
                                       input1=in1)
            if stype in _TWO_INPUT_EFFECTS:
                in1 = created.get(sd.get("input_1") or "")
                in2 = created.get(sd.get("input_2") or "")
                if in1 is None or in2 is None:
                    return None
                return coll.new_effect(name=name, type=stype, channel=ch,
                                       frame_start=fs, length=length,
                                       input1=in1, input2=in2)
        except Exception:
            return None
        return None

    _APPLY_BLACKLIST = {
        "name", "type", "channel", "frame_start",
        "filepath", "directory",
        "sound_path", "sound_name",
        "scene_ref", "scene_camera_ref",
        "input_1", "input_2",
        "length",
        "transform",
    }

    def _apply_strip_props(self, strip, sd: dict) -> None:
        for k, v in sd.items():
            if k in self._APPLY_BLACKLIST:
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
        # Per-strip Transform sub-struct.
        tr_data = sd.get("transform") or {}
        tr = getattr(strip, "transform", None)
        if tr is not None and tr_data:
            for k, v in tr_data.items():
                if not hasattr(tr, k):
                    continue
                try:
                    cur = getattr(tr, k)
                    if isinstance(cur, (int, float)):
                        setattr(tr, k, type(cur)(v))
                    elif isinstance(cur, str):
                        setattr(tr, k, v)
                    elif hasattr(cur, "__iter__") and hasattr(v, "__iter__"):
                        seq = tuple(float(x) for x in v)
                        setattr(tr, k, seq)
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

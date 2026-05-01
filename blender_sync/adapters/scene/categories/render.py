"""Render settings handler (engine, resolution, samples, output, fps...)."""
from __future__ import annotations

from typing import Any

_RENDER_FIELDS = [
    "engine", "resolution_x", "resolution_y", "resolution_percentage",
    "fps", "fps_base", "frame_start", "frame_end", "frame_step",
    "filter_size", "use_motion_blur", "motion_blur_shutter",
    "use_border", "use_crop_to_border",
    "film_transparent",
    "filepath",
    "use_compositing", "use_sequencer",
    "use_audio", "use_overwrite", "use_placeholder",
    "use_file_extension", "use_render_cache",
    "threads", "threads_mode",
    "pixel_aspect_x", "pixel_aspect_y",
    # Border crop region. The four floats are emitted only if
    # use_border is True on the sender; otherwise leaving them at the
    # default doesn't matter.
    "border_min_x", "border_min_y",
    "border_max_x", "border_max_y",
]

_IMAGE_FIELDS = [
    "file_format", "color_mode", "color_depth", "compression", "quality",
]

_VIEW_SETTINGS_FIELDS = [
    "view_transform", "look", "exposure", "gamma",
    "use_curve_mapping",
]

_VIEW_LAYER_PASS_FIELDS = [
    "use_pass_combined", "use_pass_z", "use_pass_normal",
    "use_pass_position", "use_pass_vector", "use_pass_uv",
    "use_pass_mist", "use_pass_object_index", "use_pass_material_index",
    "use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color",
    "use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_glossy_color",
    "use_pass_transmission_direct", "use_pass_transmission_indirect",
    "use_pass_emit", "use_pass_environment", "use_pass_shadow", "use_pass_ambient_occlusion",
    # Cryptomatte (4.x+) — separate object / material / asset masks. The
    # compositor relies on these for matte-based selection; missing them
    # silently breaks any cryptomatte-driven node tree.
    "use_pass_cryptomatte_object", "use_pass_cryptomatte_material",
    "use_pass_cryptomatte_asset", "use_pass_cryptomatte_accurate",
]


class RenderCategoryHandler:
    category_name = "render"

    def collect(self, ctx=None) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        scene = bpy.context.scene
        if scene is None:
            return []
        return [self._serialize(scene)]

    def _serialize(self, scene) -> dict[str, Any]:
        rs = scene.render
        out: dict[str, Any] = {
            "scene": scene.name, "render": {}, "image": {},
            "view_settings": {}, "display_settings": {},
        }
        for f in _RENDER_FIELDS:
            if hasattr(rs, f):
                try:
                    val = getattr(rs, f)
                    if isinstance(val, (int, float, bool, str)):
                        out["render"][f] = val
                except Exception:
                    pass
        if hasattr(rs, "image_settings"):
            for f in _IMAGE_FIELDS:
                if hasattr(rs.image_settings, f):
                    try:
                        val = getattr(rs.image_settings, f)
                        if isinstance(val, (int, float, bool, str)):
                            out["image"][f] = val
                    except Exception:
                        pass

        # Color Management — view_settings (Filmic/AgX/Standard, exposure, gamma)
        if hasattr(scene, "view_settings"):
            vs = scene.view_settings
            for f in _VIEW_SETTINGS_FIELDS:
                if hasattr(vs, f):
                    try:
                        val = getattr(vs, f)
                        if isinstance(val, (int, float, bool, str)):
                            out["view_settings"][f] = val
                    except Exception:
                        pass
        if hasattr(scene, "display_settings"):
            ds = scene.display_settings
            if hasattr(ds, "display_device"):
                try:
                    out["display_settings"]["display_device"] = (
                        ds.display_device
                    )
                except Exception:
                    pass

        # Per-View-Layer settings (passes, samples, use)
        view_layers = []
        for vl in getattr(scene, "view_layers", []):
            vl_data: dict[str, Any] = {
                "name": vl.name,
                "use": bool(getattr(vl, "use", True)),
            }
            for f in _VIEW_LAYER_PASS_FIELDS:
                if hasattr(vl, f):
                    try:
                        vl_data[f] = bool(getattr(vl, f))
                    except Exception:
                        pass
            if hasattr(vl, "samples"):
                try:
                    vl_data["samples"] = int(vl.samples)
                except Exception:
                    pass
            cy = getattr(vl, "cycles", None)
            if cy is not None and hasattr(cy, "samples"):
                try:
                    vl_data["cycles_samples"] = int(cy.samples)
                except Exception:
                    pass
            view_layers.append(vl_data)
        if view_layers:
            out["view_layers"] = view_layers

        if hasattr(scene, "cycles"):
            cy = scene.cycles
            cy_out: dict[str, Any] = {}
            for f in ("samples", "preview_samples", "use_denoising",
                      "use_adaptive_sampling", "adaptive_threshold",
                      "max_bounces", "transparent_max_bounces",
                      "diffuse_bounces", "glossy_bounces", "device"):
                if hasattr(cy, f):
                    try:
                        val = getattr(cy, f)
                        if isinstance(val, (int, float, bool, str)):
                            cy_out[f] = val
                    except Exception:
                        pass
            if cy_out:
                out["cycles"] = cy_out

        if hasattr(scene, "eevee"):
            ev = scene.eevee
            ev_out: dict[str, Any] = {}
            for f in ("taa_samples", "taa_render_samples",
                      "use_bloom", "use_ssr", "use_motion_blur",
                      "shadow_cube_size", "shadow_cascade_size"):
                if hasattr(ev, f):
                    try:
                        val = getattr(ev, f)
                        if isinstance(val, (int, float, bool, str)):
                            ev_out[f] = val
                    except Exception:
                        pass
            if ev_out:
                out["eevee"] = ev_out
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            scene_name = op.get("scene")
            scene = bpy.data.scenes.get(scene_name) if scene_name else bpy.context.scene
            if scene is None:
                continue
            self._apply_scene(scene, op)

    def _apply_scene(self, scene, op: dict[str, Any]) -> None:
        rs = scene.render
        for k, v in (op.get("render") or {}).items():
            if hasattr(rs, k):
                try:
                    setattr(rs, k, v)
                except Exception:
                    pass
        if hasattr(rs, "image_settings"):
            for k, v in (op.get("image") or {}).items():
                if hasattr(rs.image_settings, k):
                    try:
                        setattr(rs.image_settings, k, v)
                    except Exception:
                        pass
        if hasattr(scene, "view_settings"):
            for k, v in (op.get("view_settings") or {}).items():
                if hasattr(scene.view_settings, k):
                    try:
                        setattr(scene.view_settings, k, v)
                    except Exception:
                        pass
        if hasattr(scene, "display_settings"):
            for k, v in (op.get("display_settings") or {}).items():
                if hasattr(scene.display_settings, k):
                    try:
                        setattr(scene.display_settings, k, v)
                    except Exception:
                        pass

        wire_layers = op.get("view_layers") or []
        if wire_layers:
            target_names = [vl_data.get("name", "") for vl_data in wire_layers]
            target_set = {n for n in target_names if n}
            # Remove view layers the sender no longer has. Compositor
            # Render Layer nodes look these up by name, so leaving stale
            # ones around silently produces empty render outputs on the
            # peer side. Blender refuses to delete the last view layer,
            # so we leave at least one in place even if all are absent.
            for vl in list(scene.view_layers):
                if vl.name in target_set:
                    continue
                if len(scene.view_layers) <= 1:
                    break
                try:
                    scene.view_layers.remove(vl)
                except RuntimeError:
                    # Most common RuntimeError here is "Render layer is
                    # the active layer" — Blender prevents removing
                    # the active one. Skip and keep going.
                    pass

            for vl_data in wire_layers:
                name = vl_data.get("name")
                if not name:
                    continue
                vl = scene.view_layers.get(name)
                if vl is None:
                    try:
                        vl = scene.view_layers.new(name=name)
                    except Exception:
                        continue
                for k, v in vl_data.items():
                    if k in ("name", "cycles_samples"):
                        continue
                    if hasattr(vl, k):
                        try:
                            setattr(vl, k, v)
                        except Exception:
                            pass
                cy = getattr(vl, "cycles", None)
                if (
                    cy is not None
                    and "cycles_samples" in vl_data
                    and hasattr(cy, "samples")
                ):
                    try:
                        cy.samples = int(vl_data["cycles_samples"])
                    except Exception:
                        pass

            # Order parity. Compositor Render Layers nodes look up by
            # name (so masking still works without this), but UI and
            # the listed render order match what the sender sees only
            # after we walk the wire order and `move` each layer into
            # position.
            move = getattr(scene.view_layers, "move", None)
            if callable(move):
                for desired_idx, name in enumerate(target_names):
                    if not name:
                        continue
                    cur_idx = next(
                        (i for i, vl in enumerate(scene.view_layers)
                         if vl.name == name),
                        -1,
                    )
                    if cur_idx < 0 or cur_idx == desired_idx:
                        continue
                    try:
                        move(cur_idx, desired_idx)
                    except Exception:
                        pass
        if "cycles" in op and hasattr(scene, "cycles"):
            for k, v in op["cycles"].items():
                if hasattr(scene.cycles, k):
                    try:
                        setattr(scene.cycles, k, v)
                    except Exception:
                        pass
        if "eevee" in op and hasattr(scene, "eevee"):
            for k, v in op["eevee"].items():
                if hasattr(scene.eevee, k):
                    try:
                        setattr(scene.eevee, k, v)
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        return self.collect()

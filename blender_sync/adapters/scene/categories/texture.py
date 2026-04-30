"""Texture data block handler.

`bpy.data.textures` covers ImageTexture / EnvironmentTexture /
CloudsTexture / NoiseTexture / VoronoiTexture etc. Although most modern
Blender shading uses node-based textures, a handful of features still
rely on the legacy texture stack (modifiers, particle systems,
displacement, brushes).

We serialize the type, common primitive properties, and an
image-reference if present.
"""
from __future__ import annotations

from typing import Any

from . import _datablock_ref
from .base import DirtyContext

_PRIM = (int, float, bool, str)

_TEXTURE_BLACKLIST = {
    "rna_type", "bl_rna", "name", "type",
    "use_nodes", "node_tree", "users_material", "image_user",
}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, _PRIM):
        return value
    ref = _datablock_ref.try_ref(value)
    if ref is not None:
        return ref
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


class TextureCategoryHandler:
    category_name = "texture"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.textures):
            tex = bpy.data.textures.get(name)
            if tex is None:
                continue
            ops.append(self._serialize(tex))
        return ops

    def _serialize(self, tex) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": tex.name,
            "type": tex.type,
            "props": {},
        }
        for attr in dir(tex):
            if attr.startswith("_") or attr in _TEXTURE_BLACKLIST:
                continue
            try:
                val = getattr(tex, attr)
            except Exception:
                continue
            if callable(val):
                continue
            ser = _serialize_value(val)
            if ser is not None:
                out["props"][attr] = ser
        # Image-typed textures hold an image ref.
        img = getattr(tex, "image", None)
        if img is not None:
            ref = _datablock_ref.try_ref(img)
            if ref:
                out["image"] = ref
        return out

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            name = op.get("name", "")
            if not name:
                continue
            tex = bpy.data.textures.get(name)
            if tex is None:
                try:
                    tex = bpy.data.textures.new(name=name, type=op.get("type", "IMAGE"))
                except Exception:
                    continue
            for k, v in (op.get("props") or {}).items():
                if not hasattr(tex, k):
                    continue
                if _datablock_ref.is_ref(v):
                    resolved = _datablock_ref.resolve_ref(v)
                    if resolved is not None:
                        try:
                            setattr(tex, k, resolved)
                        except Exception:
                            pass
                    continue
                try:
                    if isinstance(v, list) and hasattr(getattr(tex, k, None), "__len__"):
                        setattr(tex, k, tuple(v))
                    else:
                        setattr(tex, k, v)
                except Exception:
                    pass
            if "image" in op and hasattr(tex, "image"):
                resolved = _datablock_ref.resolve_ref(op["image"])
                if resolved is not None:
                    try:
                        tex.image = resolved
                    except Exception:
                        pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        return [self._serialize(t) for t in bpy.data.textures]

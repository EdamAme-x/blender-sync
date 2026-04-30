"""Shared bpy data-block reference (de)serialization.

Both Modifier props and NodeTree props can hold pointer-typed values
(Object, NodeTree, Image, ...). We encode them as a sentinel string so
they survive msgpack/JSON encoding, then re-resolve on the receiver by
looking up `bpy.data.<collection>.get(name)`.

When the receiver does not yet have the referent, callers should keep
the op pending and retry later — see ReferenceResolutionQueue.
"""
from __future__ import annotations

from typing import Any

REF_PREFIX = "__bsync_ref__:"

# Mapping kind tag → bpy.data attribute name
_LOOKUP = {
    "object": "objects",
    "collection": "collections",
    "node_group": "node_groups",
    "material": "materials",
    "texture": "textures",
    "image": "images",
    "scene": "scenes",
    "movieclip": "movieclips",
    "mask": "masks",
    "world": "worlds",
    "armature": "armatures",
    "action": "actions",
}


def try_ref(value: Any) -> str | None:
    """Encode a bpy datablock reference as a sentinel string. Returns
    None if `value` is not a recognized datablock type."""
    try:
        import bpy
    except ImportError:
        return None
    if value is None:
        return None
    name = getattr(value, "name", None)
    if not isinstance(name, str):
        return None

    type_to_kind = (
        (bpy.types.Object, "object"),
        (bpy.types.Collection, "collection"),
        (bpy.types.NodeTree, "node_group"),
        (bpy.types.Material, "material"),
        (bpy.types.Texture, "texture"),
        (bpy.types.Image, "image"),
        (bpy.types.Scene, "scene"),
        (bpy.types.World, "world"),
        (bpy.types.Armature, "armature"),
        (bpy.types.Action, "action"),
    )
    for cls, kind in type_to_kind:
        try:
            if isinstance(value, cls):
                return f"{REF_PREFIX}{kind}:{name}"
        except Exception:
            pass

    movieclip = getattr(bpy.types, "MovieClip", None)
    if movieclip is not None and isinstance(value, movieclip):
        return f"{REF_PREFIX}movieclip:{name}"
    mask = getattr(bpy.types, "Mask", None)
    if mask is not None and isinstance(value, mask):
        return f"{REF_PREFIX}mask:{name}"
    return None


def is_ref(token: Any) -> bool:
    return isinstance(token, str) and token.startswith(REF_PREFIX)


def parse_ref(token: str) -> tuple[str, str] | None:
    if not is_ref(token):
        return None
    body = token[len(REF_PREFIX):]
    kind, _, name = body.partition(":")
    if not kind or not name:
        return None
    return kind, name


def resolve_ref(token: str):
    """Returns the actual bpy data block, or None if not yet present."""
    parsed = parse_ref(token)
    if parsed is None:
        return None
    kind, name = parsed
    try:
        import bpy
    except ImportError:
        return None
    attr = _LOOKUP.get(kind)
    if attr is None:
        return None
    coll = getattr(bpy.data, attr, None)
    if coll is None:
        return None
    return coll.get(name)


class ReferenceResolutionQueue:
    """Queue of pending (op, attr, token) tuples that failed to resolve
    when first received. Caller retries on each tick: any reference that
    now resolves is applied, the rest stay queued. Capped to avoid
    unbounded growth when references genuinely never arrive.
    """

    def __init__(self, capacity: int = 1024) -> None:
        self._items: list[tuple[Any, str, str, Any]] = []
        self._capacity = capacity

    def add(self, target: Any, attr: str, token: str, fallback: Any = None) -> None:
        if len(self._items) >= self._capacity:
            # Drop oldest to keep memory bounded.
            self._items.pop(0)
        self._items.append((target, attr, token, fallback))

    def retry(self) -> int:
        """Try resolving every pending reference. Returns the count of
        successfully resolved (and applied) items."""
        if not self._items:
            return 0
        applied = 0
        remaining = []
        for entry in self._items:
            target, attr, token, fallback = entry
            try:
                resolved = resolve_ref(token)
            except Exception:
                resolved = None
            if resolved is None:
                remaining.append(entry)
                continue
            try:
                setattr(target, attr, resolved)
                applied += 1
            except Exception:
                remaining.append(entry)
        self._items = remaining
        return applied

    def __len__(self) -> int:
        return len(self._items)

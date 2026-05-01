"""Deletion detection.

Blender's depsgraph does not emit a "datablock removed" event we can
reliably hook. Instead we snapshot the live name set per data category
each tick and compare to the previous snapshot — names that disappeared
are emitted as DELETE ops.

Op shape:
    {"kind": "object" | "material" | "mesh" | "image" | "collection",
     "name": <str>}

Receivers look up the named datablock and remove it. Force packets are
NOT used here — DELETE is reliable, ordered.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


_TRACKED = (
    ("object",        "objects"),
    ("material",      "materials"),
    ("mesh",          "meshes"),
    ("image",         "images"),
    ("collection",    "collections"),
    ("camera",        "cameras"),
    ("light",         "lights"),
    ("action",        "actions"),
    ("armature",      "armatures"),
    ("node_group",    "node_groups"),
    ("world",         "worlds"),
    ("texture",       "textures"),
    ("curve",         "curves"),
    ("lattice",       "lattices"),
    ("metaball",      "metaballs"),
    # GP v3 (Blender 4.3+) and legacy GP both checked; getattr returns
    # None for the unsupported one and the loop skips it.
    ("grease_pencil", "grease_pencils_v3"),
    ("grease_pencil", "grease_pencils"),
    ("particle_settings", "particles"),
    ("volume",        "volumes"),
    ("point_cloud",   "pointclouds"),
    ("sound",         "sounds"),
)


class DeletionCategoryHandler:
    category_name = "deletion"

    def __init__(self) -> None:
        self._prev: dict[str, set[str]] = {kind: set() for kind, _ in _TRACKED}
        self._initialized = False

    def collect(self, ctx: DirtyContext = None) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []

        deletions: list[dict[str, Any]] = []
        for kind, attr in _TRACKED:
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue
            current = {db.name for db in collection}
            if not self._initialized:
                self._prev[kind] = current
                continue
            removed = self._prev[kind] - current
            for name in removed:
                deletions.append({"kind": kind, "name": name})
            self._prev[kind] = current

        if not self._initialized:
            self._initialized = True
        return deletions

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            kind = op.get("kind")
            name = op.get("name")
            if not kind or not name:
                continue
            attr = next((a for k, a in _TRACKED if k == kind), None)
            if attr is None:
                continue
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue
            db = collection.get(name)
            if db is None:
                continue
            try:
                collection.remove(db, do_unlink=True)
            except TypeError:
                # Some collections (e.g. images) don't accept do_unlink.
                try:
                    collection.remove(db)
                except Exception:
                    pass
            except Exception:
                pass
            # Reset prev to reflect the apply so we don't echo this back.
            self._prev[kind].discard(name)

    def build_full(self) -> list[dict[str, Any]]:
        # No deletions to broadcast at startup; just initialize the
        # baseline so the next tick computes deltas correctly.
        try:
            import bpy
        except ImportError:
            return []
        for kind, attr in _TRACKED:
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue
            self._prev[kind] = {db.name for db in collection}
        self._initialized = True
        return []

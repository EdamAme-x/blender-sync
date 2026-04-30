"""Rename detection.

Each datablock we want to track gets a stable hidden ID property
``_bsync_uid`` that survives name changes. The handler maintains a
``uid -> name`` map per data category. When a tick observes that a uid's
associated name changed, it emits a RENAME op. Receivers find the local
datablock with the same uid and rename it to match.

This complements DELETE: together they let peers stay aligned across
arbitrary user edits.
"""
from __future__ import annotations

import uuid
from typing import Any

from .base import DirtyContext


_UID_KEY = "_bsync_uid"

_TRACKED = (
    ("object",     "objects"),
    ("material",   "materials"),
    ("collection", "collections"),
    ("image",      "images"),
    ("camera",     "cameras"),
    ("light",      "lights"),
    ("armature",   "armatures"),
    ("action",     "actions"),
    ("mesh",       "meshes"),
    ("node_group", "node_groups"),
    ("world",      "worlds"),
    ("texture",    "textures"),
    ("curve",      "curves"),
    ("lattice",    "lattices"),
    ("metaball",   "metaballs"),
)


def _read_uid(db) -> str | None:
    """Read uid without writing. Returns None if absent."""
    try:
        cur = db.get(_UID_KEY)
        if isinstance(cur, str) and cur:
            return cur
    except Exception:
        pass
    return None


def _assign_uid(db) -> str:
    """Assign and return a uid. Writes to ID Property — only call when
    we already know the datablock needs one."""
    new = uuid.uuid4().hex[:12]
    try:
        db[_UID_KEY] = new
        return new
    except Exception:
        return ""


class RenameCategoryHandler:
    category_name = "rename"

    def __init__(self) -> None:
        # uid -> last seen name, per kind
        self._last: dict[str, dict[str, str]] = {k: {} for k, _ in _TRACKED}
        # name -> uid cache (per kind) used to detect new datablocks
        # without paying ID-property writes every tick.
        self._name_to_uid: dict[str, dict[str, str]] = {k: {} for k, _ in _TRACKED}

    def collect(self, ctx: DirtyContext = None) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []

        renames: list[dict[str, Any]] = []
        for kind, attr in _TRACKED:
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue

            seen: dict[str, str] = {}
            new_name_to_uid: dict[str, str] = {}

            for db in collection:
                # Avoid writing to the datablock unless absolutely
                # necessary — that keeps the .blend file from being
                # marked dirty just because we surveyed it.
                uid = _read_uid(db)
                if uid is None:
                    # Try to recover an existing uid we previously knew
                    # this name held (so a renamed datablock keeps its
                    # uid even after a Blender reload).
                    uid = self._name_to_uid[kind].get(db.name)
                    if uid is None:
                        # Genuinely new datablock — assign a uid.
                        uid = _assign_uid(db)
                if not uid:
                    continue
                seen[uid] = db.name
                new_name_to_uid[db.name] = uid
                prev_name = self._last[kind].get(uid)
                if prev_name is not None and prev_name != db.name:
                    renames.append({
                        "kind": kind,
                        "uid": uid,
                        "old": prev_name,
                        "new": db.name,
                    })
            self._last[kind] = seen
            self._name_to_uid[kind] = new_name_to_uid
        return renames

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        for op in ops:
            kind = op.get("kind")
            uid = op.get("uid")
            new_name = op.get("new")
            if not kind or not uid or not new_name:
                continue
            attr = next((a for k, a in _TRACKED if k == kind), None)
            if attr is None:
                continue
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue

            target = None
            blocker = None
            for db in collection:
                try:
                    db_uid = db.get(_UID_KEY)
                    if db_uid == uid:
                        target = db
                    elif db.name == new_name:
                        # A different datablock already holds the target
                        # name. We must move it aside before renaming, or
                        # Blender will silently append ".001".
                        blocker = db
                except Exception:
                    pass
            if target is None:
                # Nothing here matches the uid. The op may be for a peer
                # we haven't seen yet — record the intent so the next
                # build_full_snapshot picks it up correctly.
                self._last[kind][uid] = new_name
                continue

            # If there's a name conflict with another datablock, push it
            # to a temporary unique name first.
            if blocker is not None and blocker is not target:
                tmp = f"{new_name}.bsync_tmp_{uid[:6]}"
                try:
                    blocker.name = tmp
                except Exception:
                    pass

            try:
                target.name = new_name
            except Exception:
                continue

            # Read back the actual name. Blender may have appended a
            # suffix despite our blocker handling; prefer the truth so
            # we don't echo a stale name back to peers.
            actual_name = getattr(target, "name", new_name)
            self._last[kind][uid] = actual_name

    def build_full(self) -> list[dict[str, Any]]:
        # No renames at startup; just stamp UIDs (only datablocks that
        # don't already have one) and seed the cache.
        try:
            import bpy
        except ImportError:
            return []
        for kind, attr in _TRACKED:
            collection = getattr(bpy.data, attr, None)
            if collection is None:
                continue
            self._last[kind] = {}
            self._name_to_uid[kind] = {}
            for db in collection:
                uid = _read_uid(db) or _assign_uid(db)
                if uid:
                    self._last[kind][uid] = db.name
                    self._name_to_uid[kind][db.name] = uid
        return []

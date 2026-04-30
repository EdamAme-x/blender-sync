"""Custom properties (ID Properties) shared serializer.

Blender lets users attach arbitrary properties to any data block via
``obj["my_prop"] = value``. These are widely used by pipeline tools
(Asset Browser, rigging, game engine exporters).

We serialize into a flat dict[str, primitive | list]. Reference-typed
properties (e.g. PointerProperty to another Object) are dropped — they
require the referent to be synced first, and naming collisions across
peers are not a problem this layer can solve cleanly.

Internal Blender keys starting with ``_RNA_UI`` (UI metadata) are skipped.
"""
from __future__ import annotations

from typing import Any

_PRIM = (int, float, bool, str)


def _coerce(value: Any) -> Any:
    if isinstance(value, _PRIM):
        return value
    if hasattr(value, "to_list"):
        try:
            out = value.to_list()
            if all(isinstance(v, _PRIM) for v in out):
                return out
        except Exception:
            pass
    if hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            out = list(value)
            if all(isinstance(v, _PRIM) for v in out):
                return out
        except Exception:
            pass
    return None


def serialize_id_props(datablock) -> dict[str, Any]:
    """Returns a serializable dict of custom properties on `datablock`.
    Empty dict if none."""
    out: dict[str, Any] = {}
    try:
        keys = list(datablock.keys())
    except Exception:
        return out
    for key in keys:
        if not isinstance(key, str) or key.startswith("_"):
            continue
        try:
            val = datablock[key]
        except Exception:
            continue
        coerced = _coerce(val)
        if coerced is not None:
            out[key] = coerced
    return out


def apply_id_props(datablock, props: dict[str, Any]) -> None:
    if not props:
        return
    for key, val in props.items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        try:
            datablock[key] = val
        except Exception:
            pass

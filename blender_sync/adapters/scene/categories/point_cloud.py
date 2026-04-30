"""Point Cloud data block handler.

Blender 4.x / 5.x exposes point geometry through the unified Attribute
system, not via per-Point properties. Positions live at
`pc.attributes['position'].data` (key `'vector'`) and radius lives at
`pc.attributes['radius'].data` (key `'value'`). The legacy `pc.points`
collection is read-only — resizing the cloud goes through `pc.resize()`.

We keep the wire format simple: flat `positions` and `radii` arrays
plus a `count`. Per-point custom attributes are deferred to a later
revision; geometry-nodes-driven clouds (where attributes are computed
each evaluation) need a deeper attribute walk anyway.
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


# Skip serializing position/radius arrays for clouds bigger than this.
# Joiners (initial snapshot) would otherwise stall the reliable channel
# for several seconds per huge cloud — past this size we prefer the
# explicit force_sync flow.
_BUILD_FULL_MAX_POINTS = 50_000


class PointCloudCategoryHandler:
    category_name = "point_cloud"

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        ops: list[dict[str, Any]] = []
        for name in list(ctx.point_clouds):
            pc = self._get_pc(bpy, name)
            if pc is None:
                continue
            ops.append(self._serialize(pc))
        return ops

    def _get_pc(self, bpy, name: str):
        coll = getattr(bpy.data, "pointclouds", None)
        if coll is None:
            return None
        return coll.get(name)

    def _serialize(self, pc, max_points: int | None = None) -> dict[str, Any]:
        try:
            n = len(pc.points)
        except Exception:
            n = 0
        out: dict[str, Any] = {"name": pc.name, "count": n}
        if max_points is not None and n > max_points:
            # Caller asked us to skip arrays for oversize clouds — peers
            # will need a force_sync to receive the points.
            out["truncated"] = True
            return out

        positions = self._read_attribute(pc, "position", "vector", n * 3)
        radii = self._read_attribute(pc, "radius", "value", n)
        out["positions"] = positions
        out["radii"] = radii
        return out

    def _read_attribute(self, pc, attr_name: str, prop: str, length: int) -> list[float]:
        if length <= 0:
            return []
        attr = self._get_attr(pc, attr_name)
        if attr is None:
            return []
        try:
            data = attr.data
        except Exception:
            return []
        if _HAS_NUMPY:
            try:
                buf = _np.empty(length, dtype=_np.float32)
                data.foreach_get(prop, buf)
                return buf.tolist()
            except Exception:
                pass
        # Fallback: Python loop. Slow but correct on builds without numpy.
        out: list[float] = []
        try:
            for item in data:
                v = getattr(item, prop, None)
                if v is None:
                    continue
                if hasattr(v, "__iter__"):
                    out.extend(float(x) for x in v)
                else:
                    out.append(float(v))
        except Exception:
            return []
        return out

    def _get_attr(self, pc, name: str):
        attrs = getattr(pc, "attributes", None)
        if attrs is None:
            return None
        try:
            return attrs.get(name)
        except Exception:
            try:
                return attrs[name]
            except Exception:
                return None

    def apply(self, ops: list[dict[str, Any]]) -> None:
        try:
            import bpy
        except ImportError:
            return
        coll = getattr(bpy.data, "pointclouds", None)
        if coll is None:
            return
        for op in ops:
            name = op.get("name", "")
            if not name:
                continue
            pc = coll.get(name)
            if pc is None:
                try:
                    pc = coll.new(name)
                except Exception:
                    continue

            count = int(op.get("count", 0))
            if op.get("truncated"):
                # Sender skipped the arrays; only the existence of the
                # cloud is announced. A force_sync from the sender will
                # later carry the points.
                continue
            positions = op.get("positions") or []
            radii = op.get("radii") or []

            try:
                cur = len(pc.points)
            except Exception:
                cur = 0

            if count != cur and hasattr(pc, "resize"):
                try:
                    pc.resize(size=count)
                except Exception:
                    pass

            n_now = min(count, len(pc.points) if hasattr(pc, "points") else 0)
            if n_now > 0:
                self._write_attribute(pc, "position", "vector", positions, n_now * 3)
            if n_now > 0:
                self._write_attribute(pc, "radius", "value", radii, n_now)

            try:
                pc.update_tag()
            except Exception:
                pass

    def _write_attribute(
        self, pc, attr_name: str, prop: str, values: list[float], length: int
    ) -> None:
        if length <= 0 or len(values) < length:
            return
        attr = self._get_attr(pc, attr_name)
        if attr is None:
            return
        try:
            data = attr.data
        except Exception:
            return
        if _HAS_NUMPY:
            try:
                buf = _np.array(values[:length], dtype=_np.float32)
                data.foreach_set(prop, buf)
                return
            except Exception:
                pass
        # Per-element fallback. `data[i].vector` and `data[i].value` are
        # the documented attribute accessors.
        try:
            stride = length // max(1, len(data)) if hasattr(data, "__len__") else 1
            if attr_name == "position":
                for i, item in enumerate(data):
                    base = i * 3
                    if base + 2 < length:
                        item.vector = (
                            float(values[base]),
                            float(values[base + 1]),
                            float(values[base + 2]),
                        )
            else:
                for i, item in enumerate(data):
                    if i < length:
                        item.value = float(values[i])
            del stride
        except Exception:
            pass

    def build_full(self) -> list[dict[str, Any]]:
        try:
            import bpy
        except ImportError:
            return []
        coll = getattr(bpy.data, "pointclouds", None)
        if coll is None:
            return []
        # Apply the snapshot truncation here so the initial-snapshot
        # phase doesn't stall on big clouds. Force sync still sends full
        # data because it goes through `collect()` (no max_points there).
        return [self._serialize(p, max_points=_BUILD_FULL_MAX_POINTS) for p in coll]

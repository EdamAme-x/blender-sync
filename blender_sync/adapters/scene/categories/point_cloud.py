"""Point Cloud data block handler.

Point clouds in Blender expose:
  - points.position (Vec3) — co-ordinates
  - points.radius (float) — per-point radius

We sync positions + radii via foreach_get/_set for efficiency. Custom
attributes are best-effort; complex geometry-nodes-driven point clouds
will need a deeper attribute walk in a future revision.

Sizes scale linearly with point count, so per-point hashes / chunked
diffs are a reasonable future optimization. For the first cut we send
the full array (msgpack + zstd compresses identical floats well).
"""
from __future__ import annotations

from typing import Any

from .base import DirtyContext


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

    def _serialize(self, pc) -> dict[str, Any]:
        positions: list[float] = []
        radii: list[float] = []
        n = 0
        try:
            n = len(pc.points)
        except Exception:
            n = 0
        if n > 0:
            try:
                positions = [0.0] * (n * 3)
                pc.points.foreach_get("position", positions)
            except Exception:
                positions = []
                for p in pc.points:
                    co = getattr(p, "co", None) or getattr(p, "position", None)
                    if co is None:
                        continue
                    positions.extend(float(v) for v in co)
            try:
                radii = [0.0] * n
                pc.points.foreach_get("radius", radii)
            except Exception:
                radii = []
        return {
            "name": pc.name,
            "count": n,
            "positions": positions,
            "radii": radii,
        }

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
            positions = op.get("positions") or []
            radii = op.get("radii") or []

            try:
                cur = len(pc.points)
            except Exception:
                cur = 0

            # Resize point set. Some Blender builds only expose `add()`
            # so we grow / shrink via that path. Shrinking is rare; if
            # the API doesn't support it we just overwrite the prefix.
            if count > cur and hasattr(pc.points, "add"):
                try:
                    pc.points.add(count - cur)
                except Exception:
                    pass
            elif count < cur and hasattr(pc.points, "remove"):
                try:
                    while len(pc.points) > count:
                        pc.points.remove(pc.points[-1])
                except Exception:
                    pass

            n_now = min(count, len(pc.points))
            if n_now > 0 and len(positions) >= n_now * 3:
                try:
                    pc.points.foreach_set("position", positions[: n_now * 3])
                except Exception:
                    for i in range(n_now):
                        try:
                            base = i * 3
                            pc.points[i].co = (
                                float(positions[base]),
                                float(positions[base + 1]),
                                float(positions[base + 2]),
                            )
                        except Exception:
                            pass
            if n_now > 0 and len(radii) >= n_now:
                try:
                    pc.points.foreach_set("radius", radii[:n_now])
                except Exception:
                    pass

            try:
                pc.update_tag()
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
        return [self._serialize(p) for p in coll]

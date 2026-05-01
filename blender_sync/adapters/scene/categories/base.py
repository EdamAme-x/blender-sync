"""Common protocols for scene category handlers.

Each handler maps a domain CategoryKind to bpy operations:
  - collect: gather dirty ops for sending
  - apply:   apply ops received from peers
  - build_full: produce a full snapshot for Initial Snapshot / Force Push

Some handlers depend on dirty sets (transform, material, modifier, mesh,
visibility) and some are stateless reads of singletons (render, compositor,
scene_world). The DirtyContext object lets the gateway hand the right slice
of state to each handler without each handler reaching back into the
DirtySnapshot directly.
"""
from __future__ import annotations

from typing import Any, Protocol


class DirtyContext:
    """View over a DirtySnapshot tailored for category handlers."""

    __slots__ = (
        "objects_transform", "objects_visibility",
        "materials", "modifiers",
        "meshes_committed", "meshes_editing",
        "render", "compositor", "scene_world",
        "cameras", "lights",
        "collections", "animations", "images",
        "armatures", "poses", "shape_keys",
        "grease_pencils", "curves", "particles",
        "node_groups", "textures", "lattices", "metaballs",
        "volumes", "point_clouds",
        "vse_strip",
    )

    def __init__(self, snap) -> None:
        self.objects_transform = set(snap.objects_transform)
        self.objects_visibility = set(snap.objects_visibility)
        self.materials = set(snap.materials)
        self.modifiers = {obj for obj, _ in snap.modifiers}
        self.meshes_committed = set(snap.meshes_committed)
        self.meshes_editing = set(snap.meshes_editing)
        self.render = bool(snap.render)
        self.compositor = bool(snap.compositor)
        self.scene_world = bool(snap.scene_world)
        self.cameras = set(getattr(snap, "cameras", frozenset()))
        self.lights = set(getattr(snap, "lights", frozenset()))
        self.collections = set(getattr(snap, "collections", frozenset()))
        self.animations = set(getattr(snap, "animations", frozenset()))
        self.images = set(getattr(snap, "images", frozenset()))
        self.armatures = set(getattr(snap, "armatures", frozenset()))
        self.poses = set(getattr(snap, "poses", frozenset()))
        self.shape_keys = set(getattr(snap, "shape_keys", frozenset()))
        self.grease_pencils = set(getattr(snap, "grease_pencils", frozenset()))
        self.curves = set(getattr(snap, "curves", frozenset()))
        self.particles = set(getattr(snap, "particles", frozenset()))
        self.node_groups = set(getattr(snap, "node_groups", frozenset()))
        self.textures = set(getattr(snap, "textures", frozenset()))
        self.lattices = set(getattr(snap, "lattices", frozenset()))
        self.metaballs = set(getattr(snap, "metaballs", frozenset()))
        self.volumes = set(getattr(snap, "volumes", frozenset()))
        self.point_clouds = set(getattr(snap, "point_clouds", frozenset()))
        self.vse_strip = bool(getattr(snap, "vse_strip", False))


class ICategoryHandler(Protocol):
    category_name: str

    def collect(self, ctx: DirtyContext) -> list[dict[str, Any]]: ...
    def apply(self, ops: list[dict[str, Any]]) -> None: ...
    def build_full(self) -> list[dict[str, Any]]: ...

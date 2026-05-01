from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DirtySnapshot:
    objects_transform: frozenset[str]
    objects_visibility: frozenset[str]
    materials: frozenset[str]
    modifiers: frozenset[tuple[str, str]]
    meshes_committed: frozenset[str]
    meshes_editing: frozenset[str]
    cameras: frozenset[str]
    lights: frozenset[str]
    collections: frozenset[str]
    animations: frozenset[str]
    images: frozenset[str]
    armatures: frozenset[str]
    poses: frozenset[str]
    shape_keys: frozenset[str]
    grease_pencils: frozenset[str]
    curves: frozenset[str]
    particles: frozenset[str]
    node_groups: frozenset[str]
    textures: frozenset[str]
    lattices: frozenset[str]
    metaballs: frozenset[str]
    volumes: frozenset[str]
    point_clouds: frozenset[str]
    sounds: frozenset[str]
    render: bool
    compositor: bool
    scene_world: bool
    vse_strip: bool
    view3d: bool

    def is_empty(self) -> bool:
        return (
            not self.objects_transform
            and not self.objects_visibility
            and not self.materials
            and not self.modifiers
            and not self.meshes_committed
            and not self.meshes_editing
            and not self.cameras
            and not self.lights
            and not self.collections
            and not self.animations
            and not self.images
            and not self.armatures
            and not self.poses
            and not self.shape_keys
            and not self.grease_pencils
            and not self.curves
            and not self.particles
            and not self.node_groups
            and not self.textures
            and not self.lattices
            and not self.metaballs
            and not self.volumes
            and not self.point_clouds
            and not self.sounds
            and not self.render
            and not self.compositor
            and not self.scene_world
            and not self.vse_strip
            and not self.view3d
        )


@dataclass
class DirtyTracker:
    objects_transform: set[str] = field(default_factory=set)
    objects_visibility: set[str] = field(default_factory=set)
    materials: set[str] = field(default_factory=set)
    modifiers: set[tuple[str, str]] = field(default_factory=set)
    meshes_committed: set[str] = field(default_factory=set)
    meshes_editing: set[str] = field(default_factory=set)
    cameras: set[str] = field(default_factory=set)
    lights: set[str] = field(default_factory=set)
    collections: set[str] = field(default_factory=set)
    animations: set[str] = field(default_factory=set)
    images: set[str] = field(default_factory=set)
    armatures: set[str] = field(default_factory=set)
    poses: set[str] = field(default_factory=set)
    shape_keys: set[str] = field(default_factory=set)
    grease_pencils: set[str] = field(default_factory=set)
    curves: set[str] = field(default_factory=set)
    particles: set[str] = field(default_factory=set)
    node_groups: set[str] = field(default_factory=set)
    textures: set[str] = field(default_factory=set)
    lattices: set[str] = field(default_factory=set)
    metaballs: set[str] = field(default_factory=set)
    volumes: set[str] = field(default_factory=set)
    point_clouds: set[str] = field(default_factory=set)
    sounds: set[str] = field(default_factory=set)
    render: bool = False
    compositor: bool = False
    scene_world: bool = False
    vse_strip: bool = False
    view3d: bool = False

    def mark_transform(self, obj_name: str) -> None:
        self.objects_transform.add(obj_name)

    def mark_visibility(self, obj_name: str) -> None:
        self.objects_visibility.add(obj_name)

    def mark_material(self, mat_name: str) -> None:
        self.materials.add(mat_name)

    def mark_modifier(self, obj_name: str, mod_name: str) -> None:
        self.modifiers.add((obj_name, mod_name))

    def mark_mesh_committed(self, obj_name: str) -> None:
        self.meshes_committed.add(obj_name)

    def mark_mesh_editing(self, obj_name: str) -> None:
        self.meshes_editing.add(obj_name)

    def mark_render(self) -> None:
        self.render = True

    def mark_compositor(self) -> None:
        self.compositor = True

    def mark_scene_world(self) -> None:
        self.scene_world = True

    def mark_vse_strip(self) -> None:
        self.vse_strip = True

    def mark_view3d(self) -> None:
        self.view3d = True

    def mark_camera(self, name: str) -> None:
        self.cameras.add(name)

    def mark_light(self, name: str) -> None:
        self.lights.add(name)

    def mark_collection(self, name: str) -> None:
        self.collections.add(name)

    def mark_animation(self, owner_name: str) -> None:
        self.animations.add(owner_name)

    def mark_image(self, name: str) -> None:
        self.images.add(name)

    def mark_armature(self, name: str) -> None:
        self.armatures.add(name)

    def mark_pose(self, owner_name: str) -> None:
        self.poses.add(owner_name)

    def mark_shape_keys(self, owner_name: str) -> None:
        self.shape_keys.add(owner_name)

    def mark_grease_pencil(self, name: str) -> None:
        self.grease_pencils.add(name)

    def mark_curve(self, name: str) -> None:
        self.curves.add(name)

    def mark_particle(self, owner_name: str) -> None:
        self.particles.add(owner_name)

    def mark_node_group(self, name: str) -> None:
        self.node_groups.add(name)

    def mark_texture(self, name: str) -> None:
        self.textures.add(name)

    def mark_lattice(self, name: str) -> None:
        self.lattices.add(name)

    def mark_metaball(self, name: str) -> None:
        self.metaballs.add(name)

    def mark_volume(self, name: str) -> None:
        self.volumes.add(name)

    def mark_point_cloud(self, name: str) -> None:
        self.point_clouds.add(name)

    def mark_sound(self, name: str) -> None:
        self.sounds.add(name)

    def flush(self) -> DirtySnapshot:
        snap = DirtySnapshot(
            objects_transform=frozenset(self.objects_transform),
            objects_visibility=frozenset(self.objects_visibility),
            materials=frozenset(self.materials),
            modifiers=frozenset(self.modifiers),
            meshes_committed=frozenset(self.meshes_committed),
            meshes_editing=frozenset(self.meshes_editing),
            cameras=frozenset(self.cameras),
            lights=frozenset(self.lights),
            collections=frozenset(self.collections),
            animations=frozenset(self.animations),
            images=frozenset(self.images),
            armatures=frozenset(self.armatures),
            poses=frozenset(self.poses),
            shape_keys=frozenset(self.shape_keys),
            grease_pencils=frozenset(self.grease_pencils),
            curves=frozenset(self.curves),
            particles=frozenset(self.particles),
            node_groups=frozenset(self.node_groups),
            textures=frozenset(self.textures),
            lattices=frozenset(self.lattices),
            metaballs=frozenset(self.metaballs),
            volumes=frozenset(self.volumes),
            point_clouds=frozenset(self.point_clouds),
            sounds=frozenset(self.sounds),
            render=self.render,
            compositor=self.compositor,
            scene_world=self.scene_world,
            vse_strip=self.vse_strip,
            view3d=self.view3d,
        )
        self.objects_transform.clear()
        self.objects_visibility.clear()
        self.materials.clear()
        self.modifiers.clear()
        self.meshes_committed.clear()
        self.meshes_editing.clear()
        self.cameras.clear()
        self.lights.clear()
        self.collections.clear()
        self.animations.clear()
        self.images.clear()
        self.armatures.clear()
        self.poses.clear()
        self.shape_keys.clear()
        self.grease_pencils.clear()
        self.curves.clear()
        self.particles.clear()
        self.node_groups.clear()
        self.textures.clear()
        self.lattices.clear()
        self.metaballs.clear()
        self.volumes.clear()
        self.point_clouds.clear()
        self.sounds.clear()
        self.render = False
        self.compositor = False
        self.scene_world = False
        self.vse_strip = False
        self.view3d = False
        return snap

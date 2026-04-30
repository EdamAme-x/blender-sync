from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy.types import PropertyGroup


class SyncSessionState(PropertyGroup):
    status: StringProperty(name="Status", default="idle")
    token: StringProperty(name="Token", default="")
    join_token: StringProperty(name="Join Token", default="")
    error: StringProperty(name="Error", default="")
    peer_id: StringProperty(name="Peer ID", default="")
    manual_answer_input: StringProperty(name="Manual Answer", default="")

    sync_transform: BoolProperty(name="Transform", default=True)
    sync_material: BoolProperty(name="Material", default=True)
    sync_modifier: BoolProperty(name="Modifier", default=True)
    sync_compositor: BoolProperty(name="Compositor", default=True)
    sync_render: BoolProperty(name="Render", default=True)
    sync_scene_world: BoolProperty(name="Scene/World", default=True)
    sync_visibility: BoolProperty(name="Visibility", default=True)
    sync_camera: BoolProperty(name="Camera", default=True)
    sync_light: BoolProperty(name="Light", default=True)
    sync_collection: BoolProperty(name="Collection", default=True)
    sync_animation: BoolProperty(name="Animation", default=True)
    sync_image: BoolProperty(name="Image", default=True)
    sync_armature: BoolProperty(name="Armature", default=True)
    sync_pose: BoolProperty(name="Pose", default=True)
    sync_shape_keys: BoolProperty(name="Shape Keys", default=True)
    sync_constraints: BoolProperty(name="Constraints", default=True)
    sync_grease_pencil: BoolProperty(name="Grease Pencil", default=True)
    sync_curve: BoolProperty(name="Curve", default=True)
    sync_particle: BoolProperty(name="Particle", default=True)
    sync_node_group: BoolProperty(name="Node Group", default=True)
    sync_texture: BoolProperty(name="Texture", default=True)
    sync_lattice: BoolProperty(name="Lattice", default=True)
    sync_metaball: BoolProperty(name="Metaball", default=True)
    sync_volume: BoolProperty(name="Volume", default=True)
    sync_point_cloud: BoolProperty(name="Point Cloud", default=True)

    conflict_policy: bpy.props.EnumProperty(
        name="Conflict Policy",
        items=[
            ("auto_lww",       "Auto (LWW)",     "Last write wins"),
            ("local_wins",     "Local Wins",     "Reject remote in conflict window"),
            ("remote_wins",    "Remote Wins",    "Apply remote in conflict window"),
            ("peer_priority",  "Peer Priority",  "Use peer ID order"),
            ("manual",         "Manual",         "Pop a dialog per conflict"),
        ],
        default="auto_lww",
    )
    conflict_window: bpy.props.FloatProperty(
        name="Conflict Window (s)", default=2.0, min=0.1, max=60.0,
    )
    conflict_peer_priority: bpy.props.StringProperty(
        name="Peer Priority (comma)", default="",
    )

    latency_ms: bpy.props.FloatProperty(name="Latency (ms)", default=0.0)
    bandwidth_kbps: bpy.props.FloatProperty(name="Bandwidth (KB/s)", default=0.0)
    peer_count: bpy.props.IntProperty(name="Peer Count", default=0)

    mesh_on_edit_exit: BoolProperty(name="Mesh: On Exit Edit", default=True)
    mesh_during_edit: BoolProperty(name="Mesh: During Edit", default=False)
    mesh_edit_hz: FloatProperty(
        name="Edit-mode Hz", default=5.0, min=1.0, max=30.0
    )


CLASSES = (SyncSessionState,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blender_sync_state = bpy.props.PointerProperty(type=SyncSessionState)


def unregister():
    if hasattr(bpy.types.Scene, "blender_sync_state"):
        del bpy.types.Scene.blender_sync_state
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

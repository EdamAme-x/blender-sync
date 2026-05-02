from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as _
from bpy.types import Panel


class SYNC_PT_main(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blender Sync"
    bl_label = "Blender Sync"
    bl_idname = "SYNC_PT_main"

    def draw(self, context):
        layout = self.layout
        state = context.scene.blender_sync_state
        status = state.status

        # Status box (always visible at the top).
        box = layout.box()
        box.label(text=_("Status: %s") % _(status))
        if state.error:
            box.label(text=_("Error: %s") % state.error, icon="ERROR")

        # State-driven UI: only show what's relevant for the current
        # state so the user isn't presented with "Start Sharing" while
        # already sharing, "Join Existing" while connected, etc.
        if status in ("idle", "error"):
            self._draw_idle_section(layout, state)
        elif status in ("sharing", "awaiting_answer"):
            self._draw_sharing_section(layout, state)
        elif status == "awaiting_manual_answer":
            self._draw_manual_section(layout, state)
        elif status == "connecting":
            layout.separator()
            layout.label(text="Connecting…", icon="SORTTIME")
        elif status == "live":
            self._draw_live_section(layout, state)

        # Disconnect is shown in every state except idle/error so the
        # user can always abort.
        if status not in ("idle", "error"):
            layout.separator()
            layout.operator("blender_sync.disconnect", icon="X")

    # ---- per-state sections -------------------------------------------------

    def _draw_idle_section(self, layout, state):
        layout.separator()
        col = layout.column(align=True)
        col.operator("blender_sync.start_sharing", icon="WORLD")

        layout.separator()
        col2 = layout.column(align=True)
        col2.label(text=_("Join Existing:"))
        col2.prop(state, "join_token", text="")
        col2.operator("blender_sync.join_session", icon="LINKED")

    def _draw_sharing_section(self, layout, state):
        layout.separator()
        box = layout.box()
        box.label(text=_("Share Token:"), icon="WORLD")
        box.prop(state, "token", text="")
        box.operator("blender_sync.copy_token", icon="COPYDOWN")
        if state.status == "awaiting_answer":
            box.label(text="Waiting for peer to join…", icon="SORTTIME")

    def _draw_manual_section(self, layout, state):
        layout.separator()
        # 1) Our offer token (long manual SDP token).
        box1 = layout.box()
        box1.label(text=_("Share Token:"), icon="WORLD")
        box1.prop(state, "token", text="")
        box1.operator("blender_sync.copy_token", icon="COPYDOWN")

        layout.separator()
        # 2) Manual fallback explanation + paste field for peer's
        # answer token.
        box2 = layout.box()
        box2.label(text=_("Manual SDP fallback active"), icon="ERROR")
        col_help = box2.column(align=True)
        col_help.label(text=_("Nostr relay was unreachable."))
        col_help.label(text=_("1. Copy the token above and send it to the peer."))
        col_help.label(text=_("2. Paste the peer's reply token below."))
        box2.separator()
        box2.prop(state, "manual_answer_input", text="")
        box2.operator("blender_sync.submit_manual_answer", icon="IMPORT")

    def _draw_live_section(self, layout, state):
        layout.separator()
        metrics = layout.box()
        metrics.label(text="Connection Metrics", icon="INFO")
        mc = metrics.column(align=True)
        mc.label(text="Peers: %d" % int(state.peer_count))
        mc.label(text="Latency: %.1f ms" % float(state.latency_ms))
        mc.label(text="Bandwidth: %.1f KB/s" % float(state.bandwidth_kbps))

        layout.separator()
        box = layout.box()
        box.label(text="Force Sync", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.operator("blender_sync.force_push", text="Push", icon="EXPORT")
        row.operator("blender_sync.force_pull", text="Pull", icon="IMPORT")


class SYNC_PT_filters(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blender Sync"
    bl_label = "Sync Filters"
    bl_idname = "SYNC_PT_filters"
    bl_parent_id = "SYNC_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        state = context.scene.blender_sync_state

        col = layout.column(align=True)
        col.prop(state, "sync_transform")
        col.prop(state, "sync_material")
        col.prop(state, "sync_modifier")
        col.prop(state, "sync_compositor")
        col.prop(state, "sync_render")
        col.prop(state, "sync_scene_world")
        col.prop(state, "sync_visibility")
        col.prop(state, "sync_camera")
        col.prop(state, "sync_light")
        col.prop(state, "sync_collection")
        col.prop(state, "sync_animation")
        col.prop(state, "sync_image")
        col.prop(state, "sync_armature")
        col.prop(state, "sync_pose")
        col.prop(state, "sync_shape_keys")
        col.prop(state, "sync_constraints")
        col.prop(state, "sync_grease_pencil")
        col.prop(state, "sync_curve")
        col.prop(state, "sync_particle")
        col.prop(state, "sync_node_group")
        col.prop(state, "sync_texture")
        col.prop(state, "sync_lattice")
        col.prop(state, "sync_metaball")
        col.prop(state, "sync_volume")
        col.prop(state, "sync_point_cloud")
        col.prop(state, "sync_vse_strip")
        col.prop(state, "sync_sound")
        col.prop(state, "sync_view3d")

        layout.separator()
        layout.label(text="Mesh:")
        col2 = layout.column(align=True)
        col2.prop(state, "mesh_on_edit_exit")
        col2.prop(state, "mesh_during_edit")
        sub = col2.row()
        sub.enabled = state.mesh_during_edit
        sub.prop(state, "mesh_edit_hz")

        layout.separator()
        layout.label(text="Conflict Resolution:")
        col3 = layout.column(align=True)
        col3.prop(state, "conflict_policy", text="")
        col3.prop(state, "conflict_window")
        if state.conflict_policy == "peer_priority":
            col3.prop(state, "conflict_peer_priority", text="")


CLASSES = (SYNC_PT_main, SYNC_PT_filters)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

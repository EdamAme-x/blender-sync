from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as _
from bpy.types import Operator


def _container():
    from .. import _runtime
    return _runtime.runtime


def _status() -> str:
    rt = _container()
    if rt is None:
        return "idle"
    try:
        return rt.session.status.value
    except Exception:
        return "idle"


_IDLE_STATES = {"idle", "error"}
_LIVE_STATES = {"live"}
_BUSY_STATES = {"sharing", "awaiting_answer", "awaiting_manual_answer", "connecting"}


class SYNC_OT_start_sharing(Operator):
    bl_idname = "blender_sync.start_sharing"
    bl_label = "Start Sharing"
    bl_description = "Generate a share token and wait for a peer to join"

    @classmethod
    def poll(cls, context):
        return _status() in _IDLE_STATES

    def execute(self, context):
        rt = _container()
        if rt is None:
            self.report({"ERROR"}, _("Sync runtime is not initialized"))
            return {"CANCELLED"}
        try:
            rt.start_sharing()
        except Exception as exc:
            self.report({"ERROR"}, f"start_sharing failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SYNC_OT_join_session(Operator):
    bl_idname = "blender_sync.join_session"
    bl_label = "Join Session"
    bl_description = "Join an existing session using a token"

    @classmethod
    def poll(cls, context):
        return _status() in _IDLE_STATES

    def execute(self, context):
        rt = _container()
        if rt is None:
            self.report({"ERROR"}, _("Sync runtime is not initialized"))
            return {"CANCELLED"}
        state = context.scene.blender_sync_state
        token = (state.join_token or "").strip()
        if not token:
            self.report({"ERROR"}, _("Token is empty"))
            return {"CANCELLED"}
        try:
            rt.join_session(token)
        except Exception as exc:
            self.report({"ERROR"}, f"join failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SYNC_OT_disconnect(Operator):
    bl_idname = "blender_sync.disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from the current sync session"

    @classmethod
    def poll(cls, context):
        return _status() not in _IDLE_STATES

    def execute(self, context):
        rt = _container()
        if rt is None:
            return {"CANCELLED"}
        try:
            rt.disconnect()
        except Exception as exc:
            self.report({"ERROR"}, f"disconnect failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SYNC_OT_copy_token(Operator):
    bl_idname = "blender_sync.copy_token"
    bl_label = "Copy Token"
    bl_description = "Copy the current share token to clipboard"

    @classmethod
    def poll(cls, context):
        try:
            return bool(context.scene.blender_sync_state.token)
        except Exception:
            return False

    def execute(self, context):
        state = context.scene.blender_sync_state
        token = state.token
        if not token:
            self.report({"WARNING"}, _("No token to copy"))
            return {"CANCELLED"}
        bpy.context.window_manager.clipboard = token
        self.report({"INFO"}, _("Token copied to clipboard"))
        return {"FINISHED"}


class SYNC_OT_submit_manual_answer(Operator):
    bl_idname = "blender_sync.submit_manual_answer"
    bl_label = "Submit Manual Answer"
    bl_description = "Paste an answer token from the joining peer"

    @classmethod
    def poll(cls, context):
        return _status() == "awaiting_manual_answer"

    def execute(self, context):
        rt = _container()
        if rt is None:
            return {"CANCELLED"}
        state = context.scene.blender_sync_state
        sdp_token = (state.manual_answer_input or "").strip()
        if not sdp_token:
            self.report({"ERROR"}, _("Empty answer token"))
            return {"CANCELLED"}
        try:
            rt.submit_manual_answer(sdp_token)
        except Exception as exc:
            self.report({"ERROR"}, f"submit failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SYNC_OT_force_push(Operator):
    bl_idname = "blender_sync.force_push"
    bl_label = "Force Push (My Scene -> All)"
    bl_description = (
        "Overwrite all peers with MY current scene state. "
        "Bypasses last-write-wins. Honors Sync Filters."
    )

    @classmethod
    def poll(cls, context):
        return _status() in _LIVE_STATES

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rt = _container()
        if rt is None:
            return {"CANCELLED"}
        try:
            rt.force_push()
        except Exception as exc:
            self.report({"ERROR"}, f"force push failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, _("Force pushed local scene to peers"))
        return {"FINISHED"}


class SYNC_OT_force_pull(Operator):
    bl_idname = "blender_sync.force_pull"
    bl_label = "Force Pull (Receive from peers)"
    bl_description = (
        "Ask peers to send their state and overwrite MY scene. "
        "Bypasses last-write-wins. Honors Sync Filters."
    )

    @classmethod
    def poll(cls, context):
        return _status() in _LIVE_STATES

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rt = _container()
        if rt is None:
            return {"CANCELLED"}
        try:
            rt.force_pull()
        except Exception as exc:
            self.report({"ERROR"}, f"force pull failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, _("Force pull request sent to peers"))
        return {"FINISHED"}


CLASSES = (
    SYNC_OT_start_sharing,
    SYNC_OT_join_session,
    SYNC_OT_disconnect,
    SYNC_OT_copy_token,
    SYNC_OT_submit_manual_answer,
    SYNC_OT_force_push,
    SYNC_OT_force_pull,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

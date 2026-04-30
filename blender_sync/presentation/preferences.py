from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as _
from bpy.props import StringProperty
from bpy.types import AddonPreferences


class SyncAddonPreferences(AddonPreferences):
    bl_idname = "blender_sync"

    stun_url: StringProperty(
        name="STUN URL",
        default="stun:stun.l.google.com:19302",
    )
    turn_url: StringProperty(name="TURN URL", default="")
    turn_username: StringProperty(name="TURN Username", default="")
    turn_password: StringProperty(
        name="TURN Password", default="", subtype="PASSWORD"
    )
    relays: StringProperty(
        name="Nostr Relays (comma-separated)",
        default="wss://relay.damus.io,wss://nostr.wine,wss://relay.nostr.band,wss://nos.lol",
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text=_("ICE Servers"))
        col.prop(self, "stun_url")
        col.prop(self, "turn_url")
        col.prop(self, "turn_username")
        col.prop(self, "turn_password")
        col.separator()
        col.label(text=_("Signaling"))
        col.prop(self, "relays")


def register():
    bpy.utils.register_class(SyncAddonPreferences)


def unregister():
    bpy.utils.unregister_class(SyncAddonPreferences)

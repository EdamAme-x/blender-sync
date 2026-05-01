from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChannelKind(str, Enum):
    RELIABLE = "reliable"
    FAST = "fast"


class CategoryKind(str, Enum):
    TRANSFORM = "transform"
    MATERIAL = "material"
    MODIFIER = "modifier"
    MESH = "mesh"
    COMPOSITOR = "compositor"
    RENDER = "render"
    SCENE = "scene"
    VISIBILITY = "visibility"
    CAMERA = "camera"
    LIGHT = "light"
    MATERIAL_SLOTS = "material_slots"
    COLLECTION = "collection"
    ANIMATION = "animation"
    IMAGE = "image"
    DELETION = "deletion"
    RENAME = "rename"
    ARMATURE = "armature"
    POSE = "pose"
    SHAPE_KEYS = "shape_keys"
    CONSTRAINTS = "constraints"
    GREASE_PENCIL = "grease_pencil"
    CURVE = "curve"
    PARTICLE = "particle"
    NODE_GROUP = "node_group"
    TEXTURE = "texture"
    LATTICE = "lattice"
    METABALL = "metaball"
    VOLUME = "volume"
    POINT_CLOUD = "point_cloud"
    VSE_STRIP = "vse_strip"
    SOUND = "sound"
    SNAPSHOT = "snapshot"
    CONTROL = "control"


class ControlOpKind(str, Enum):
    PING = "ping"
    PONG = "pong"
    PULL_REQUEST = "pull_request"
    HELLO = "hello"
    # NACK: receiver requests a missing seq range. payload: {"from": int, "to": int}
    NACK = "nack"
    # RESEND: sender re-emits a previously-sent reliable packet. payload is
    # the original packet's to_wire_dict() to keep chain coherent.
    RESEND = "resend"


CATEGORY_TO_CHANNEL: dict[CategoryKind, ChannelKind] = {
    CategoryKind.TRANSFORM: ChannelKind.FAST,
    CategoryKind.MATERIAL: ChannelKind.RELIABLE,
    CategoryKind.MODIFIER: ChannelKind.RELIABLE,
    CategoryKind.MESH: ChannelKind.RELIABLE,
    CategoryKind.COMPOSITOR: ChannelKind.RELIABLE,
    CategoryKind.RENDER: ChannelKind.RELIABLE,
    CategoryKind.SCENE: ChannelKind.RELIABLE,
    CategoryKind.VISIBILITY: ChannelKind.RELIABLE,
    CategoryKind.CAMERA: ChannelKind.RELIABLE,
    CategoryKind.LIGHT: ChannelKind.RELIABLE,
    CategoryKind.MATERIAL_SLOTS: ChannelKind.RELIABLE,
    CategoryKind.COLLECTION: ChannelKind.RELIABLE,
    CategoryKind.ANIMATION: ChannelKind.RELIABLE,
    CategoryKind.IMAGE: ChannelKind.RELIABLE,
    CategoryKind.DELETION: ChannelKind.RELIABLE,
    CategoryKind.RENAME: ChannelKind.RELIABLE,
    CategoryKind.ARMATURE: ChannelKind.RELIABLE,
    # POSE updates can be 60Hz during animation playback; keep them on
    # the fast lane like transforms.
    CategoryKind.POSE: ChannelKind.FAST,
    CategoryKind.SHAPE_KEYS: ChannelKind.RELIABLE,
    CategoryKind.CONSTRAINTS: ChannelKind.RELIABLE,
    CategoryKind.GREASE_PENCIL: ChannelKind.RELIABLE,
    CategoryKind.CURVE: ChannelKind.RELIABLE,
    CategoryKind.PARTICLE: ChannelKind.RELIABLE,
    CategoryKind.NODE_GROUP: ChannelKind.RELIABLE,
    CategoryKind.TEXTURE: ChannelKind.RELIABLE,
    CategoryKind.LATTICE: ChannelKind.RELIABLE,
    CategoryKind.METABALL: ChannelKind.RELIABLE,
    CategoryKind.VOLUME: ChannelKind.RELIABLE,
    CategoryKind.POINT_CLOUD: ChannelKind.RELIABLE,
    CategoryKind.VSE_STRIP: ChannelKind.RELIABLE,
    CategoryKind.SOUND: ChannelKind.RELIABLE,
    CategoryKind.SNAPSHOT: ChannelKind.RELIABLE,
    CategoryKind.CONTROL: ChannelKind.RELIABLE,
}


class SessionStatus(str, Enum):
    IDLE = "idle"
    SHARING = "sharing"
    AWAITING_ANSWER = "awaiting_answer"
    AWAITING_MANUAL_ANSWER = "awaiting_manual_answer"
    CONNECTING = "connecting"
    LIVE = "live"
    ERROR = "error"


@dataclass(frozen=True)
class Peer:
    peer_id: str
    label: str = ""


@dataclass
class Session:
    local_peer: Peer
    status: SessionStatus = SessionStatus.IDLE
    room_id: str | None = None
    token: str | None = None
    remote_peers: dict[str, Peer] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class SyncOp:
    category: CategoryKind
    payload: dict[str, Any]


@dataclass(frozen=True)
class Packet:
    version: int
    seq: int
    ts: float
    author: str
    category: CategoryKind
    ops: tuple[dict[str, Any], ...]
    force: bool = False
    # Rolling Adler-style chain checksum of all RELIABLE packets sent by
    # `author` up to and including this one. Receivers verify by replaying
    # the chain locally; mismatch / gap triggers a NACK + RESEND.
    # Always 0 on FAST channel packets (transforms intentionally lossy).
    chain: int = 0
    # Single-digit checksum (chain mod 10) for readable debug output.
    digit: int = 0

    @property
    def channel(self) -> ChannelKind:
        return CATEGORY_TO_CHANNEL[self.category]

    def to_wire_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "v": self.version,
            "seq": self.seq,
            "ts": self.ts,
            "author": self.author,
            "ch": self.category.value,
            "ops": list(self.ops),
        }
        if self.force:
            out["f"] = 1
        if self.chain:
            out["c"] = self.chain
            out["d"] = self.digit
        return out

    @classmethod
    def from_wire_dict(cls, d: dict[str, Any]) -> "Packet":
        return cls(
            version=int(d["v"]),
            seq=int(d["seq"]),
            ts=float(d["ts"]),
            author=str(d["author"]),
            category=CategoryKind(d["ch"]),
            ops=tuple(d.get("ops", [])),
            force=bool(d.get("f", 0)),
            chain=int(d.get("c", 0)),
            digit=int(d.get("d", 0)),
        )


@dataclass
class MeshSyncMode:
    on_edit_exit: bool = True
    during_edit: bool = False
    edit_mode_hz: float = 5.0


@dataclass
class SyncFilters:
    transform: bool = True
    material: bool = True
    modifier: bool = True
    mesh: MeshSyncMode = field(default_factory=MeshSyncMode)
    compositor: bool = True
    render: bool = True
    scene_world: bool = True
    visibility: bool = True
    camera: bool = True
    light: bool = True
    collection: bool = True
    animation: bool = True
    image: bool = True
    armature: bool = True
    pose: bool = True
    shape_keys: bool = True
    constraints: bool = True
    grease_pencil: bool = True
    curve: bool = True
    particle: bool = True
    node_group: bool = True
    texture: bool = True
    lattice: bool = True
    metaball: bool = True
    volume: bool = True
    point_cloud: bool = True
    vse_strip: bool = True
    sound: bool = True

    def enabled_categories(self) -> frozenset["CategoryKind"]:
        out: set[CategoryKind] = set()
        if self.transform: out.add(CategoryKind.TRANSFORM)
        if self.visibility: out.add(CategoryKind.VISIBILITY)
        if self.material:
            out.add(CategoryKind.MATERIAL)
            out.add(CategoryKind.MATERIAL_SLOTS)
        if self.modifier: out.add(CategoryKind.MODIFIER)
        if self.mesh.on_edit_exit or self.mesh.during_edit:
            out.add(CategoryKind.MESH)
        if self.compositor: out.add(CategoryKind.COMPOSITOR)
        if self.render: out.add(CategoryKind.RENDER)
        if self.scene_world: out.add(CategoryKind.SCENE)
        if self.camera: out.add(CategoryKind.CAMERA)
        if self.light: out.add(CategoryKind.LIGHT)
        if self.collection: out.add(CategoryKind.COLLECTION)
        if self.animation: out.add(CategoryKind.ANIMATION)
        if self.image: out.add(CategoryKind.IMAGE)
        if self.armature: out.add(CategoryKind.ARMATURE)
        if self.pose: out.add(CategoryKind.POSE)
        if self.shape_keys: out.add(CategoryKind.SHAPE_KEYS)
        if self.constraints: out.add(CategoryKind.CONSTRAINTS)
        if self.grease_pencil: out.add(CategoryKind.GREASE_PENCIL)
        if self.curve: out.add(CategoryKind.CURVE)
        if self.particle: out.add(CategoryKind.PARTICLE)
        if self.node_group: out.add(CategoryKind.NODE_GROUP)
        if self.texture: out.add(CategoryKind.TEXTURE)
        if self.lattice: out.add(CategoryKind.LATTICE)
        if self.metaball: out.add(CategoryKind.METABALL)
        if self.volume: out.add(CategoryKind.VOLUME)
        if self.point_cloud: out.add(CategoryKind.POINT_CLOUD)
        if self.vse_strip: out.add(CategoryKind.VSE_STRIP)
        if self.sound: out.add(CategoryKind.SOUND)
        # Deletion + rename are always enabled — removing them would let
        # stale state accumulate on peers indefinitely.
        out.add(CategoryKind.DELETION)
        out.add(CategoryKind.RENAME)
        return frozenset(out)


@dataclass(frozen=True)
class IceServer:
    url: str
    username: str | None = None
    credential: str | None = None


@dataclass
class TransportConfig:
    ice_servers: tuple[IceServer, ...] = ()


@dataclass
class SignalingConfig:
    nostr_relays: tuple[str, ...] = (
        "wss://relay.damus.io",
        "wss://nostr.wine",
        "wss://relay.nostr.band",
        "wss://nos.lol",
    )
    # Time budget for the Nostr signaling round-trip after the initial offer
    # is published. Includes peer's gather + answer + relay propagation.
    # Too short causes unnecessary fallback to manual SDP; too long delays
    # the manual fallback UX.
    nostr_timeout_seconds: float = 30.0
    answer_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class OfferPreparation:
    """Result of an ISignalingProvider preparing to receive an answer.

    - `share_token` is what the user copies and sends to the peer.
    - `post_status` is the SessionStatus the runtime should display while
      waiting for the answer. Different providers expose different waits:
        * Nostr: AWAITING_ANSWER (relay round-trip)
        * Manual: AWAITING_MANUAL_ANSWER (user pastes back)
    """
    share_token: str
    post_status: SessionStatus


@dataclass
class ConflictResolutionConfig:
    # Default policy at session start. UI can change this without
    # restarting the session.
    policy: str = "auto_lww"  # ConflictPolicy enum value
    window_seconds: float = 2.0
    # Comma-separated peer ids ordered most-priority -> least.
    peer_priority: tuple[str, ...] = ()


@dataclass
class SyncConfig:
    peer_id: str
    transport: TransportConfig = field(default_factory=TransportConfig)
    signaling: SignalingConfig = field(default_factory=SignalingConfig)
    filters: SyncFilters = field(default_factory=SyncFilters)
    conflict: ConflictResolutionConfig = field(
        default_factory=ConflictResolutionConfig,
    )
    tick_interval_seconds: float = 1.0 / 60.0
    inbound_max_per_tick: int = 20
    compression_min_bytes: int = 256

"""Tests for Force Sync (Push/Pull + control message dispatch)."""
import asyncio
import json

from blender_sync.domain.entities import (
    CategoryKind,
    ChannelKind,
    ControlOpKind,
    Packet,
    Peer,
    Session,
    SessionStatus,
    SyncConfig,
    SyncFilters,
)
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.domain.policies.packet_builder import PacketBuilder, SeqCounter
from blender_sync.usecases.apply_remote import ApplyRemotePacketUseCase
from blender_sync.usecases.force_sync import (
    ControlMessageHandler,
    ForcePullUseCase,
    ForcePushUseCase,
)
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.clock import FakeClock
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway
from tests.fakes.transport import InMemoryTransport


class _JsonCodec:
    def encode(self, packet):
        return json.dumps(packet.to_wire_dict()).encode("utf-8")

    def decode(self, data):
        return Packet.from_wire_dict(json.loads(data.decode("utf-8")))


def _setup():
    asyncio.set_event_loop(asyncio.new_event_loop())
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    builder = PacketBuilder("me", SeqCounter())
    push = ForcePushUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    pull = ForcePullUseCase(
        transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    return scene, transport, cfg, builder, push, pull


def test_force_push_skips_when_not_live():
    scene, transport, cfg, builder, push, _ = _setup()
    session = Session(local_peer=Peer("me"), status=SessionStatus.IDLE)
    scene.snapshot = [(CategoryKind.TRANSFORM, [{"n": "Cube"}])]
    sent = push.execute(session)
    assert sent == 0
    assert transport.sent == []


def test_force_push_sends_only_enabled_categories():
    scene, transport, cfg, builder, push, _ = _setup()
    cfg.filters = SyncFilters(transform=True, material=False)
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    scene.snapshot = [
        (CategoryKind.TRANSFORM, [{"n": "Cube", "loc": [1, 2, 3]}]),
        (CategoryKind.MATERIAL, [{"mat": "Mat.001"}]),
    ]
    sent = push.execute(session)
    assert sent == 1
    assert len(transport.sent) == 1
    channel, data = transport.sent[0]
    decoded = _JsonCodec().decode(data)
    assert decoded.category is CategoryKind.TRANSFORM
    assert decoded.force is True


def test_force_push_packet_marked_force():
    scene, transport, cfg, builder, push, _ = _setup()
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    scene.snapshot = [(CategoryKind.RENDER, [{"render": {"engine": "CYCLES"}}])]
    push.execute(session)
    decoded = _JsonCodec().decode(transport.sent[0][1])
    assert decoded.force is True
    assert decoded.author == "me"


def test_force_pull_sends_control_packet():
    scene, transport, cfg, builder, push, pull = _setup()
    cfg.filters = SyncFilters(transform=True, material=True, modifier=False)
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    ok = pull.execute(session)
    assert ok is True
    assert len(transport.sent) == 1
    channel, data = transport.sent[0]
    assert channel is ChannelKind.RELIABLE
    decoded = _JsonCodec().decode(data)
    assert decoded.category is CategoryKind.CONTROL
    assert decoded.ops[0]["type"] == ControlOpKind.PULL_REQUEST.value
    cats = set(decoded.ops[0]["categories"])
    assert "transform" in cats and "material" in cats
    assert "modifier" not in cats


def test_apply_remote_force_bypasses_lww():
    scene = FakeSceneGateway()
    codec = _JsonCodec()
    echo = EchoFilter(self_peer_id="me")
    lww = LWWResolver()
    cfg = SyncConfig(peer_id="me")
    uc = ApplyRemotePacketUseCase(scene, codec, echo, lww, RecordingLogger(), cfg)

    # First, an old normal packet establishes high seq from alice.
    p_high = Packet(1, 100, 200.0, "alice", CategoryKind.TRANSFORM,
                    ({"n": "Cube", "loc": [9, 9, 9]},))
    uc.apply_raw(codec.encode(p_high))
    assert len(scene.applied) == 1

    # A non-force packet with lower seq is rejected by LWW.
    p_old = Packet(1, 50, 100.0, "alice", CategoryKind.TRANSFORM,
                   ({"n": "Cube", "loc": [0, 0, 0]},))
    uc.apply_raw(codec.encode(p_old))
    assert len(scene.applied) == 1  # unchanged

    # A force packet with even older ts/seq must apply unconditionally.
    p_force = Packet(1, 10, 50.0, "alice", CategoryKind.TRANSFORM,
                     ({"n": "Cube", "loc": [1, 2, 3]},), force=True)
    uc.apply_raw(codec.encode(p_force))
    assert len(scene.applied) == 2
    assert scene.applied[1][1][0]["loc"] == [1, 2, 3]


def test_control_pull_request_triggers_force_push():
    scene, transport, cfg, builder, push, pull = _setup()
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    scene.snapshot = [(CategoryKind.TRANSFORM, [{"n": "Cube"}])]

    handler = ControlMessageHandler(
        push, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder,
    )
    handler.handle(session, [{"type": ControlOpKind.PULL_REQUEST.value,
                               "categories": ["transform"]}])

    # Force push should have fired -> 1 transform packet sent
    assert len(transport.sent) == 1
    decoded = _JsonCodec().decode(transport.sent[0][1])
    assert decoded.category is CategoryKind.TRANSFORM
    assert decoded.force is True

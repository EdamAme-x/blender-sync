import asyncio
import json

from blender_sync.domain.entities import (
    CategoryKind,
    Peer,
    Session,
    SessionStatus,
    SyncConfig,
)
from blender_sync.domain.policies.packet_builder import PacketBuilder, SeqCounter
from blender_sync.usecases.sync_tick import SyncTickUseCase
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.clock import FakeClock
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway
from tests.fakes.transport import InMemoryTransport


class _JsonCodec:
    def encode(self, packet):
        return json.dumps(packet.to_wire_dict()).encode("utf-8")

    def decode(self, data):
        from blender_sync.domain.entities import Packet
        return Packet.from_wire_dict(json.loads(data.decode("utf-8")))


def test_sync_tick_sends_when_dirty():
    asyncio.set_event_loop(asyncio.new_event_loop())
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    seq = SeqCounter()
    builder = PacketBuilder("me", seq)
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)

    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube", "loc": [1, 2, 3]}]
    uc.tick(session)

    assert len(transport.sent) == 1
    channel, data = transport.sent[0]
    assert channel.value == "fast"
    assert b"Cube" in data


def test_sync_tick_skips_when_not_live():
    scene = FakeSceneGateway()
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    builder = PacketBuilder("me", SeqCounter())
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.IDLE)
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube"}]
    uc.tick(session)
    assert transport.sent == []


def test_sync_tick_skips_when_applying_remote():
    scene = FakeSceneGateway()
    scene.applying_remote = True
    transport = InMemoryTransport()
    cfg = SyncConfig(peer_id="me")
    builder = PacketBuilder("me", SeqCounter())
    uc = SyncTickUseCase(
        scene, transport, _JsonCodec(), FakeClock(),
        RecordingLogger(), ImmediateAsyncRunner(), builder, cfg,
    )
    session = Session(local_peer=Peer("me"), status=SessionStatus.LIVE)
    scene.dirty[CategoryKind.TRANSFORM] = [{"n": "Cube"}]
    uc.tick(session)
    assert transport.sent == []

from blender_sync.domain.entities import CategoryKind, Packet, SyncConfig
from blender_sync.domain.policies.echo_filter import EchoFilter
from blender_sync.domain.policies.lww_resolver import LWWResolver
from blender_sync.usecases.apply_remote import ApplyRemotePacketUseCase
from tests.fakes.logger import RecordingLogger
from tests.fakes.scene_gateway import FakeSceneGateway


class _SimpleCodec:
    def __init__(self):
        self._packets = {}

    def encode(self, packet):
        key = id(packet).to_bytes(8, "little")
        self._packets[key] = packet
        return key

    def decode(self, data):
        return self._packets[data]


def _make_uc(self_peer_id="peer_me"):
    scene = FakeSceneGateway()
    codec = _SimpleCodec()
    echo = EchoFilter(self_peer_id=self_peer_id)
    lww = LWWResolver()
    logger = RecordingLogger()
    cfg = SyncConfig(peer_id=self_peer_id)
    return ApplyRemotePacketUseCase(scene, codec, echo, lww, logger, cfg), scene, codec


def test_apply_remote_accepts_other_peer():
    uc, scene, codec = _make_uc()
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="peer_other",
        category=CategoryKind.TRANSFORM,
        ops=({"n": "Cube", "loc": [1, 2, 3]},),
    )
    raw = codec.encode(pkt)
    uc.apply_raw(raw)
    assert len(scene.applied) == 1
    cat, ops = scene.applied[0]
    assert cat is CategoryKind.TRANSFORM
    assert ops[0]["n"] == "Cube"


def test_apply_remote_rejects_echo():
    uc, scene, codec = _make_uc(self_peer_id="me")
    pkt = Packet(
        version=1, seq=1, ts=1.0, author="me",
        category=CategoryKind.TRANSFORM, ops=({"n": "Cube"},),
    )
    uc.apply_raw(codec.encode(pkt))
    assert scene.applied == []


def test_apply_remote_lww_blocks_old():
    uc, scene, codec = _make_uc()
    p1 = Packet(1, 5, 100.0, "alice", CategoryKind.TRANSFORM, ({"n": "Cube"},))
    p2 = Packet(1, 4, 99.0, "alice", CategoryKind.TRANSFORM, ({"n": "Cube"},))
    uc.apply_raw(codec.encode(p1))
    uc.apply_raw(codec.encode(p2))
    assert len(scene.applied) == 1

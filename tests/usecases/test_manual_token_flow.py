"""Manual SDP token flow integration test (in-memory, no network)."""
import asyncio

from blender_sync.adapters.codec.token_codec import Base58TokenCodec
from blender_sync.adapters.signaling.manual_token_provider import (
    ManualTokenSignalingProvider,
)
from blender_sync.adapters.signaling.signaling_pool import SignalingPool
from blender_sync.domain.entities import (
    Peer,
    Session,
    SessionStatus,
    SyncConfig,
)
from blender_sync.usecases.join_session import JoinSessionUseCase
from blender_sync.usecases.start_sharing import StartSharingUseCase
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.logger import RecordingLogger
from tests.fakes.transport import InMemoryTransport


class _NoopEvents:
    def __init__(self):
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.tokens: list[str] = []

    def on_status(self, status):
        self.statuses.append(status)

    def on_token(self, token):
        self.tokens.append(token)

    def on_peer_joined(self, peer):
        pass

    def on_peer_left(self, peer_id):
        pass

    def on_error(self, error):
        self.errors.append(error)

    def on_disconnected(self):
        pass


class _FailingNostr:
    name = "nostr"

    async def prepare_offer(self, room_id, sdp, token_codec):
        raise RuntimeError("relay unreachable")

    async def publish_offer(self, room_id, sdp):
        raise RuntimeError("relay unreachable")

    async def wait_offer(self, room_id, timeout):
        raise RuntimeError("relay unreachable")

    async def publish_answer(self, room_id, sdp):
        raise RuntimeError("relay unreachable")

    async def wait_answer(self, room_id, timeout):
        raise RuntimeError("relay unreachable")

    async def close(self):
        pass


def _make_runner() -> ImmediateAsyncRunner:
    asyncio.set_event_loop(asyncio.new_event_loop())
    return ImmediateAsyncRunner()


def test_start_sharing_falls_back_to_manual_when_nostr_fails():
    logger = RecordingLogger()
    transport = InMemoryTransport()
    nostr = _FailingNostr()
    manual = ManualTokenSignalingProvider(logger)
    providers = [nostr, manual]
    token_codec = Base58TokenCodec()
    events = _NoopEvents()
    cfg = SyncConfig(peer_id="peer_offerer")
    cfg.signaling.nostr_timeout_seconds = 0.5

    runner = _make_runner()
    uc = StartSharingUseCase(
        transport, providers, token_codec, logger, events, runner, cfg
    )
    session = Session(local_peer=Peer("peer_offerer"))

    async def driver():
        async def submit_later():
            await asyncio.sleep(0.05)
            answer_sdp = "v=0\no=answerer 1 1 IN IP4 0.0.0.0\ns=-\n"
            manual.submit_answer(answer_sdp)
        asyncio.create_task(submit_later())
        await uc._execute_async(session)

    asyncio.get_event_loop().run_until_complete(driver())

    assert session.status is SessionStatus.LIVE
    assert session.token is not None
    assert session.token.startswith("bsync_m1_")
    assert any("nostr" in r[1] for r in logger.records)


def test_join_with_manual_token():
    logger = RecordingLogger()
    transport = InMemoryTransport()
    nostr = _FailingNostr()
    manual = ManualTokenSignalingProvider(logger)
    providers = [nostr, manual]
    token_codec = Base58TokenCodec()
    events = _NoopEvents()
    cfg = SyncConfig(peer_id="peer_joiner")

    sdp_offer = "v=0\no=offerer 1 1 IN IP4 0.0.0.0\ns=-\n"
    manual_token = token_codec.encode_manual(sdp_offer)

    runner = _make_runner()
    uc = JoinSessionUseCase(
        transport, providers, token_codec, logger, events, runner, cfg
    )
    session = Session(local_peer=Peer("peer_joiner"))

    asyncio.get_event_loop().run_until_complete(
        uc._execute_async(session, manual_token)
    )

    # The joiner's manual flow produces an answer token for the user to
    # ferry back to the offerer; the live state arrives only when the
    # offerer accepts that answer (out of band for this test).
    assert session.status is SessionStatus.AWAITING_MANUAL_ANSWER
    assert session.token is not None
    assert session.token.startswith("bsync_m1_")

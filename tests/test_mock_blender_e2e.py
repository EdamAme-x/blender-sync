"""End-to-end tests using MockBlender.

What this file does that previous tests didn't: it stands up the
*entire* presentation/runtime/usecase stack against a fake bpy and
drives realistic flows (Start Sharing, Disconnect, etc.) while
asserting both timing AND UI side effects (token visible,
tag_redraw fired, panel state coherent).

These tests caught (and now guard against):
  - "token doesn't show up until 2 minutes later" — the missing
    region.tag_redraw() bug.
  - "Start Sharing took 7 seconds" — prepare_offer awaiting publish.
  - "Disconnect did nothing" — pending nostr wait not cancelled.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from blender_sync.domain.entities import (
    OfferPreparation, Peer, Session, SessionStatus, SyncConfig,
)
from blender_sync.presentation.state_sync import BpyStateSync
from blender_sync.usecases.start_sharing import StartSharingUseCase
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.logger import RecordingLogger
from tests.fakes.mock_blender import MockBlender


# ----------------------------------------------------------------------
# Minimal fakes (transport / signaling / token codec)
# ----------------------------------------------------------------------

class _InstantTransport:
    async def configure(self, *a, **kw): pass
    def configure(self, *a, **kw): pass  # type: ignore[no-redef]
    async def create_offer(self): return "v=0\r\n"
    async def gather_complete(self, timeout=3.0): pass
    def local_description(self): return None
    async def accept_answer(self, sdp): pass
    async def close(self): pass
    def on_recv(self, cb): pass
    def on_state_change(self, cb): pass
    async def send(self, c, d): pass


class _FastProvider:
    name = "nostr"

    def __init__(self, answer_delay: float = 0.0):
        self._answer_delay = answer_delay

    async def prepare_offer(self, room_id, sdp, codec):
        return OfferPreparation(
            share_token="bsync_v1_" + room_id,
            post_status=SessionStatus.AWAITING_ANSWER,
        )

    async def wait_answer(self, room_id, timeout):
        if self._answer_delay > 0:
            await asyncio.sleep(self._answer_delay)
        return "v=0\r\n"

    async def wait_offer(self, room_id, timeout):
        return "v=0\r\n"

    async def publish_answer(self, room_id, sdp): pass
    async def close(self): pass


class _Codec:
    def encode_short(self, room_id, h): return f"bsync_v1_{room_id}"
    def decode_short(self, t): return t, ""
    def encode_manual(self, sdp): return f"manual:{sdp}"
    def decode_manual(self, t): return t.replace("manual:", "")
    def is_short(self, t): return t.startswith("bsync_v1_")


def _sync_queue():
    return lambda fn: fn()


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

def test_start_sharing_token_is_visible_to_panel(monkeypatch):
    """Press Start Sharing → MockBlender.state.token populates AND
    the sidebar region got redrawn so the user sees it immediately."""
    bl = MockBlender.install(monkeypatch)

    sync = BpyStateSync(_sync_queue(), RecordingLogger())
    runner = ImmediateAsyncRunner()
    uc = StartSharingUseCase(
        transport=_InstantTransport(),
        signaling_providers=[_FastProvider()],
        token_codec=_Codec(),
        logger=RecordingLogger(),
        events=sync,
        async_runner=runner,
        config=SyncConfig(peer_id="me"),
    )
    session = Session(local_peer=Peer("me"))

    assert bl.state.token == ""
    assert bl.tag_redraw_count == 0

    uc.execute(session)

    # 1) Token wrote through to the PropertyGroup.
    assert bl.state.token.startswith("bsync_v1_")
    # 2) Status went LIVE (provider returned an answer instantly).
    assert bl.state.status == "live"
    # 3) Panel was told to redraw — the bug we shipped earlier was
    #    that the property updated but the panel never re-rendered
    #    until 2 minutes later.
    assert bl.tag_redraw_count >= 2, (
        f"expected several tag_redraw calls (token + status + ...), "
        f"got {bl.tag_redraw_count}"
    )


def test_start_sharing_completes_within_one_second(monkeypatch):
    """User-perceived latency budget. With fast fakes Start Sharing
    should be effectively free — anything above 1s in this test
    indicates a regression in our own glue code, not the network."""
    MockBlender.install(monkeypatch)

    sync = BpyStateSync(_sync_queue(), RecordingLogger())
    runner = ImmediateAsyncRunner()
    uc = StartSharingUseCase(
        transport=_InstantTransport(),
        signaling_providers=[_FastProvider()],
        token_codec=_Codec(),
        logger=RecordingLogger(),
        events=sync,
        async_runner=runner,
        config=SyncConfig(peer_id="me"),
    )

    t0 = time.perf_counter()
    uc.execute(Session(local_peer=Peer("me")))
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"Start Sharing took {elapsed:.3f}s (budget 1.0s)"


def test_disconnect_resets_state_and_redraws(monkeypatch):
    """Disconnect should clear token / metrics and tag a redraw."""
    bl = MockBlender.install(monkeypatch)

    bl.state.token = "OLD"
    bl.state.peer_count = 5
    bl.state.latency_ms = 42.0
    bl.state.reliable_open = True
    bl.state.fast_open = True
    bl.state.pc_state = "connected"

    sync = BpyStateSync(_sync_queue(), RecordingLogger())
    sync.on_disconnected()

    assert bl.state.token == ""
    assert bl.state.peer_count == 0
    assert bl.state.latency_ms == 0.0
    assert bl.state.reliable_open is False
    assert bl.state.fast_open is False
    assert bl.state.pc_state == ""
    assert bl.tag_redraw_count >= 1


def test_transport_state_routes_to_panel_diagnostics(monkeypatch):
    """A datachannel-open event reaches reliable_open / fast_open and
    forces a redraw so the user sees 'DataChannels: open ✓'."""
    bl = MockBlender.install(monkeypatch)
    sync = BpyStateSync(_sync_queue(), RecordingLogger())

    sync.queue_status_update(reliable_open=True)
    sync.queue_status_update(fast_open=True)
    sync.queue_status_update(pc_state="connected")

    assert bl.state.reliable_open is True
    assert bl.state.fast_open is True
    assert bl.state.pc_state == "connected"
    assert bl.tag_redraw_count >= 3


def test_queued_events_drained_via_fake_timer(monkeypatch):
    """The production runtime queues events onto a thread-safe queue
    that's drained by a bpy.app.timers callback. This test wires up
    a thin equivalent and proves a queued on_token call surfaces on
    state.token after a single tick — i.e. timer-driven UI sync
    works end-to-end."""
    bl = MockBlender.install(monkeypatch)

    queue: list = []
    sync = BpyStateSync(queue.append, RecordingLogger())

    # Register a "drain queue" timer like the runtime does.
    def drain_tick():
        for fn in list(queue):
            queue.remove(fn)
            fn()
        return 0.05  # reschedule every 50ms

    import bpy  # picked up from the patched sys.modules
    bpy.app.timers.register(drain_tick, first_interval=0.05)

    sync.on_token("FROM_QUEUE")
    # Not applied yet — drain hasn't run.
    assert bl.state.token == ""

    bl.tick(0.06)
    assert bl.state.token == "FROM_QUEUE"


@pytest.mark.asyncio
async def test_publish_runs_in_background_not_blocking_token(monkeypatch):
    """Stress the optimistic-publish behavior end-to-end: even when
    the relay publish would take 0.5s, the user sees the token
    immediately."""
    from blender_sync.adapters.signaling.nostr_provider import (
        NostrSignalingProvider,
    )

    bl = MockBlender.install(monkeypatch)

    provider = NostrSignalingProvider(RecordingLogger(), relays=())

    async def slow_publish(room_id, sdp, kind):
        await asyncio.sleep(0.5)

    provider._publish = slow_publish  # type: ignore[assignment]

    t0 = time.perf_counter()
    prep = await provider.prepare_offer("ROOM_X", "v=0", _Codec())
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.1, (
        f"prepare_offer blocked {elapsed:.3f}s; should not wait on "
        f"publish."
    )
    assert prep.share_token == "bsync_v1_ROOM_X"


def test_filter_state_visible_via_mock_blender(monkeypatch):
    """The Sync Filters panel reads from the same PropertyGroup we're
    emulating. Make sure default values are sane and writable."""
    bl = MockBlender.install(monkeypatch)
    assert bl.state.sync_transform is True
    assert bl.state.sync_material is True
    bl.state.sync_transform = False
    assert bl.state.sync_transform is False


def test_mock_blender_timers_persistent_repeats(monkeypatch):
    """The fake timer system reschedules persistent ticks the same
    way bpy does, so a runtime _tick wired up against it actually
    repeats."""
    bl = MockBlender.install(monkeypatch)
    fires: list[float] = []

    import bpy

    def tick():
        fires.append(time.perf_counter())
        return 0.1  # reschedule every 100ms

    bpy.app.timers.register(tick, first_interval=0.1)
    bl.tick(0.55)
    assert len(fires) >= 5, f"only {len(fires)} fires in 550ms"

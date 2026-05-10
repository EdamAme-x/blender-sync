"""Performance regression guards for the Start Sharing / Join paths.

User feedback: "token 作るのと参加があほ遅い". The cause was a chain
of small fixed-timeout waits stacking up:

  - aiortc gather_complete capped at 8.0s
  - nostr_provider.connect_all per-relay timeout 5.0s
  - nostr_provider._safe_send recv() ack timeout 2.0s
  - prepare_offer awaited the full publish before returning the
    user-visible token

These tests pin the cumulative latency the user sees BEFORE a token
is shown, so future changes can't silently add more stalls. They use
fakes for transport / signaling so the budgets are measuring our
code, not network conditions.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from blender_sync.adapters.signaling.nostr_provider import (
    NostrSignalingProvider,
)
from blender_sync.domain.entities import (
    OfferPreparation, Peer, Session, SessionStatus, SyncConfig,
)
from blender_sync.usecases.start_sharing import StartSharingUseCase
from tests.fakes.async_runner import ImmediateAsyncRunner
from tests.fakes.logger import RecordingLogger


# Budgets in seconds. Keep these conservative; they're CI-friendly
# but tight enough that real regressions trip them.
TOKEN_BUDGET_S = 1.0   # Start Sharing -> token visible
JOIN_BUDGET_S = 1.0    # Join -> answer ready


# ----------------------------------------------------------------------
# Fast fakes (no IO)
# ----------------------------------------------------------------------

class _InstantTransport:
    """Returns SDP synchronously and reports gather complete instantly."""
    async def configure(self, *a, **kw): pass
    def configure(self, *a, **kw): pass  # type: ignore[no-redef]
    async def create_offer(self): return "v=0\r\nm=application 9 DTLS/SCTP 5000\r\n"
    async def create_answer(self, sdp): return "v=0\r\nm=application 9 DTLS/SCTP 5000\r\n"
    async def gather_complete(self, timeout=3.0): pass
    def local_description(self): return None
    async def accept_answer(self, sdp): pass
    async def close(self): pass
    def on_recv(self, cb): pass
    def on_state_change(self, cb): pass
    async def send(self, channel, data): pass


class _RecordingProvider:
    """Returns OfferPreparation immediately. Records when prepare_offer
    was called vs. when wait_answer started."""
    name = "nostr"

    def __init__(self) -> None:
        self.t_prepare_done: float | None = None
        self.t_wait_started: float | None = None

    async def prepare_offer(self, room_id, sdp, token_codec):
        self.t_prepare_done = time.perf_counter()
        return OfferPreparation(
            share_token="bsync_" + room_id,
            post_status=SessionStatus.AWAITING_ANSWER,
        )

    async def wait_answer(self, room_id, timeout):
        self.t_wait_started = time.perf_counter()
        return "v=0\r\n"

    async def wait_offer(self, room_id, timeout):
        return "v=0\r\n"

    async def publish_answer(self, room_id, sdp): pass

    async def close(self): pass


class _NoopTokenCodec:
    def encode_short(self, room_id, _h): return f"bsync_{room_id}"
    def decode_short(self, t): return t, ""
    def encode_manual(self, sdp): return f"manual:{sdp}"
    def decode_manual(self, t): return t.replace("manual:", "")
    def is_short(self, t): return t.startswith("bsync_")


class _NoopEvents:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.token_at: float | None = None

    def on_status(self, _): pass
    def on_token(self, t):
        self.tokens.append(t)
        self.token_at = time.perf_counter()
    def on_peer_joined(self, _): pass
    def on_peer_left(self, _): pass
    def on_error(self, _): pass
    def on_disconnected(self): pass


# ----------------------------------------------------------------------
# Critical-path budget tests
# ----------------------------------------------------------------------

def test_start_sharing_token_within_budget():
    """End-to-end: pressing Start Sharing must produce a token in
    well under 1 second when nothing is blocked. Regression sentinel
    for the publish-blocking-token bug we just fixed."""
    events = _NoopEvents()
    provider = _RecordingProvider()
    runner = ImmediateAsyncRunner()

    uc = StartSharingUseCase(
        transport=_InstantTransport(),
        signaling_providers=[provider],
        token_codec=_NoopTokenCodec(),
        logger=RecordingLogger(),
        events=events,
        async_runner=runner,
        config=SyncConfig(peer_id="me"),
    )
    session = Session(local_peer=Peer("me"))

    t0 = time.perf_counter()
    uc.execute(session)
    elapsed = time.perf_counter() - t0

    assert events.tokens, "no token was emitted"
    assert events.token_at is not None
    token_latency = events.token_at - t0
    assert token_latency < TOKEN_BUDGET_S, (
        f"token took {token_latency:.3f}s "
        f"(budget {TOKEN_BUDGET_S}s)"
    )
    assert elapsed < TOKEN_BUDGET_S


def test_gather_complete_default_is_three_seconds():
    """The user-facing "token is slow" report was largely a
    gather_complete(timeout=8.0) tax. Lock the value at 3.0s so a
    refactor can't silently regress it."""
    import inspect
    from blender_sync.usecases import start_sharing as ss
    src = inspect.getsource(ss)
    # Straightforward textual check — readable enough for the test
    # to fail loudly if someone bumps the value.
    assert "gather_complete(timeout=3.0)" in src, (
        "StartSharingUseCase.gather_complete should be 3.0s; "
        "increasing it makes Start Sharing visibly slower."
    )

    from blender_sync.usecases import join_session as js
    src = inspect.getsource(js)
    assert "gather_complete(timeout=3.0)" in src, (
        "JoinSessionUseCase.gather_complete should be 3.0s."
    )


# ----------------------------------------------------------------------
# Nostr-specific: prepare_offer must NOT await publish
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nostr_prepare_offer_returns_before_publish_completes():
    """The point of the optimistic-publish fix: the token comes back
    even if publish would otherwise stall on a slow relay. We use a
    delayed-send fake to prove prepare_offer doesn't wait on it."""
    logger = RecordingLogger()

    # Inject a NostrSignalingProvider configured to talk to nothing.
    # We patch the publish path to take 1 second so a synchronous
    # dependency would make prepare_offer take ≥ 1 second too.
    provider = NostrSignalingProvider(logger, relays=())

    publish_durations: list[float] = []
    publish_done = asyncio.Event()

    async def slow_publish(room_id, sdp, kind):
        t0 = time.perf_counter()
        await asyncio.sleep(0.5)
        publish_durations.append(time.perf_counter() - t0)
        publish_done.set()

    provider._publish = slow_publish  # type: ignore[assignment]

    codec = _NoopTokenCodec()

    t0 = time.perf_counter()
    prep = await provider.prepare_offer("room123", "v=0", codec)
    elapsed = time.perf_counter() - t0

    # Must return well before the 0.5s slow_publish would've finished.
    assert elapsed < 0.1, (
        f"prepare_offer blocked for {elapsed:.3f}s; should return "
        f"immediately and let publish run in the background."
    )
    assert prep.share_token == "bsync_room123"
    assert prep.post_status is SessionStatus.AWAITING_ANSWER

    # Background task should still complete.
    await asyncio.wait_for(publish_done.wait(), timeout=2.0)
    assert publish_durations and publish_durations[0] >= 0.5


# ----------------------------------------------------------------------
# Sanity: the public token shape doesn't change with the new path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nostr_prepare_offer_token_format_unchanged():
    """Make sure switching to optimistic publish didn't alter what
    peers see."""
    logger = RecordingLogger()
    provider = NostrSignalingProvider(logger, relays=())
    provider._publish = lambda *a, **kw: asyncio.sleep(0)  # type: ignore[assignment]

    prep = await provider.prepare_offer("ROOM", "sdp", _NoopTokenCodec())
    assert prep.share_token.startswith("bsync_")
    assert "ROOM" in prep.share_token

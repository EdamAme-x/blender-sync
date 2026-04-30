"""Tests for the conflict resolution policies."""
from __future__ import annotations

from blender_sync.domain.policies.conflict_resolver import (
    AutoLWWResolver,
    ConflictContext,
    ConflictDecision,
    ConflictPolicy,
    LocalWinsResolver,
    ManualResolver,
    PeerPriorityResolver,
    RemoteWinsResolver,
)


def _ctx(
    *,
    self_peer_id: str = "me",
    incoming_author: str = "alice",
    incoming_seq: int = 5,
    incoming_ts: float = 100.0,
    local_last_edit_ts: float | None = 99.0,
    local_last_seq: int | None = 4,
    local_last_author: str | None = "me",
    now_ts: float = 100.0,
    key: str = "transform:Cube",
) -> ConflictContext:
    return ConflictContext(
        key=key, self_peer_id=self_peer_id,
        incoming_author=incoming_author,
        incoming_seq=incoming_seq, incoming_ts=incoming_ts,
        local_last_edit_ts=local_last_edit_ts,
        local_last_seq=local_last_seq,
        local_last_author=local_last_author,
        now_ts=now_ts,
    )


def test_auto_lww_accepts_newer_ts():
    r = AutoLWWResolver()
    assert r.decide(_ctx(incoming_ts=200.0)) is ConflictDecision.APPLY


def test_auto_lww_rejects_older_ts():
    r = AutoLWWResolver()
    assert r.decide(_ctx(incoming_ts=50.0)) is ConflictDecision.REJECT


def test_auto_lww_accepts_when_no_local_state():
    r = AutoLWWResolver()
    assert r.decide(
        _ctx(local_last_edit_ts=None, local_last_seq=None,
             local_last_author=None)
    ) is ConflictDecision.APPLY


def test_local_wins_rejects_inside_window():
    r = LocalWinsResolver(window_seconds=2.0)
    assert r.decide(_ctx(incoming_ts=200.0, now_ts=100.0)) is ConflictDecision.REJECT


def test_local_wins_falls_back_to_lww_outside_window():
    r = LocalWinsResolver(window_seconds=1.0)
    ctx = _ctx(incoming_ts=200.0, local_last_edit_ts=50.0, now_ts=100.0)
    assert r.decide(ctx) is ConflictDecision.APPLY


def test_remote_wins_accepts_inside_window_even_when_older():
    r = RemoteWinsResolver(window_seconds=2.0)
    assert r.decide(_ctx(incoming_ts=50.0)) is ConflictDecision.APPLY


def test_remote_wins_falls_back_to_lww_outside_window():
    r = RemoteWinsResolver(window_seconds=1.0)
    # outside window (now=100, local=10, gap=90 > 1) AND incoming older
    # than local (incoming_ts=5 < local_ts=10) -> LWW says reject
    ctx = _ctx(incoming_ts=5.0, local_last_edit_ts=10.0, now_ts=100.0)
    assert r.decide(ctx) is ConflictDecision.REJECT


def test_peer_priority_higher_wins_inside_window():
    r = PeerPriorityResolver(
        priority_order=("alice", "me"), window_seconds=2.0
    )
    assert r.decide(_ctx(incoming_author="alice")) is ConflictDecision.APPLY


def test_peer_priority_lower_loses_inside_window():
    r = PeerPriorityResolver(
        priority_order=("me", "alice"), window_seconds=2.0
    )
    assert r.decide(_ctx(incoming_author="alice")) is ConflictDecision.REJECT


def test_peer_priority_unlisted_fall_back_to_lww():
    r = PeerPriorityResolver(priority_order=(), window_seconds=2.0)
    ctx = _ctx(incoming_ts=50.0)
    assert r.decide(ctx) is ConflictDecision.REJECT


def test_peer_priority_outside_window_uses_lww():
    r = PeerPriorityResolver(
        priority_order=("alice", "me"), window_seconds=1.0
    )
    # outside window AND incoming older -> LWW rejects despite alice priority
    ctx = _ctx(
        incoming_author="alice", incoming_ts=5.0,
        local_last_edit_ts=10.0, now_ts=100.0,
    )
    assert r.decide(ctx) is ConflictDecision.REJECT


def test_manual_defers_inside_window():
    r = ManualResolver(window_seconds=2.0)
    decision = r.decide(_ctx())
    assert decision is ConflictDecision.DEFER
    assert len(r.pending) == 1


def test_manual_resolved_pending_returns_user_decision():
    r = ManualResolver(window_seconds=2.0)
    ctx = _ctx()
    r.decide(ctx)
    r.resolve_pending(ctx.key, ConflictDecision.APPLY)
    assert r.decide(_ctx(incoming_ts=ctx.incoming_ts + 1)) is ConflictDecision.APPLY


def test_manual_outside_window_uses_lww():
    r = ManualResolver(window_seconds=1.0)
    ctx = _ctx(local_last_edit_ts=10.0, now_ts=100.0, incoming_ts=200.0)
    assert r.decide(ctx) is ConflictDecision.APPLY
    assert r.pending == []


def test_manual_dedup_pending_for_same_key():
    r = ManualResolver(window_seconds=2.0)
    r.decide(_ctx(key="transform:Cube"))
    r.decide(_ctx(key="transform:Cube", incoming_ts=101.0))
    assert len(r.pending) == 1


def test_resolvers_expose_policy():
    assert AutoLWWResolver().policy is ConflictPolicy.AUTO_LWW
    assert LocalWinsResolver().policy is ConflictPolicy.LOCAL_WINS
    assert RemoteWinsResolver().policy is ConflictPolicy.REMOTE_WINS
    assert PeerPriorityResolver().policy is ConflictPolicy.PEER_PRIORITY
    assert ManualResolver().policy is ConflictPolicy.MANUAL

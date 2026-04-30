"""Conflict resolution policies.

When two peers edit the same property within a small time window we
treat the situation as a *conflict*. The resolver decides whose update
wins. Five strategies, all implementing the same Protocol so the
runtime can swap them without UseCase changes:

  - AUTO_LWW       — last-write-wins on (ts, seq, author). Default.
  - LOCAL_WINS     — incoming op is dropped during the conflict window.
  - REMOTE_WINS    — incoming op overrides ours; our seq/ts is bumped
                     so we don't echo back.
  - PEER_PRIORITY  — a configured peer-id ordering decides.
  - MANUAL         — incoming op is parked for user adjudication.

A conflict is "near in time" only — outside the window we always defer
to LWW so non-overlapping edits stay deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class ConflictPolicy(str, Enum):
    AUTO_LWW = "auto_lww"
    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    PEER_PRIORITY = "peer_priority"
    MANUAL = "manual"


class ConflictDecision(str, Enum):
    APPLY = "apply"          # use incoming op
    REJECT = "reject"        # ignore incoming op
    DEFER = "defer"          # park for later (manual UI)


@dataclass
class ConflictContext:
    """Evidence presented to a resolver when deciding a single op."""
    key: str            # e.g. "transform:Cube"
    self_peer_id: str
    incoming_author: str
    incoming_seq: int
    incoming_ts: float
    local_last_edit_ts: float | None  # None if local hasn't touched key
    local_last_seq: int | None
    local_last_author: str | None
    now_ts: float


@runtime_checkable
class IConflictResolver(Protocol):
    policy: ConflictPolicy

    def decide(self, ctx: ConflictContext) -> ConflictDecision: ...


def _is_in_window(ctx: ConflictContext, window: float) -> bool:
    if ctx.local_last_edit_ts is None:
        return False
    return abs(ctx.now_ts - ctx.local_last_edit_ts) <= window


def _lww_wins(ctx: ConflictContext) -> bool:
    """Standard tuple comparison used by AUTO_LWW."""
    if ctx.local_last_edit_ts is None or ctx.local_last_seq is None:
        return True
    incoming = (ctx.incoming_ts, ctx.incoming_seq, ctx.incoming_author)
    local = (
        ctx.local_last_edit_ts, ctx.local_last_seq,
        ctx.local_last_author or "",
    )
    return incoming > local


@dataclass
class AutoLWWResolver(IConflictResolver):
    policy: ConflictPolicy = ConflictPolicy.AUTO_LWW

    def decide(self, ctx: ConflictContext) -> ConflictDecision:
        return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT


@dataclass
class LocalWinsResolver(IConflictResolver):
    policy: ConflictPolicy = ConflictPolicy.LOCAL_WINS
    window_seconds: float = 2.0

    def decide(self, ctx: ConflictContext) -> ConflictDecision:
        if _is_in_window(ctx, self.window_seconds):
            return ConflictDecision.REJECT
        return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT


@dataclass
class RemoteWinsResolver(IConflictResolver):
    policy: ConflictPolicy = ConflictPolicy.REMOTE_WINS
    window_seconds: float = 2.0

    def decide(self, ctx: ConflictContext) -> ConflictDecision:
        if _is_in_window(ctx, self.window_seconds):
            return ConflictDecision.APPLY
        return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT


@dataclass
class PeerPriorityResolver(IConflictResolver):
    policy: ConflictPolicy = ConflictPolicy.PEER_PRIORITY
    # Ordered list of peer ids — earlier entries beat later ones during a
    # conflict window. Peers absent from the list rank below all listed
    # entries and tie-break with LWW among themselves.
    priority_order: tuple[str, ...] = ()
    window_seconds: float = 2.0

    def decide(self, ctx: ConflictContext) -> ConflictDecision:
        if not _is_in_window(ctx, self.window_seconds):
            return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT

        local_rank = self._rank(ctx.self_peer_id)
        remote_rank = self._rank(ctx.incoming_author)
        if remote_rank == local_rank:
            return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT
        return ConflictDecision.APPLY if remote_rank < local_rank else ConflictDecision.REJECT

    def _rank(self, peer_id: str) -> int:
        for i, p in enumerate(self.priority_order):
            if p == peer_id:
                return i
        return 1_000_000


@dataclass
class ManualResolver(IConflictResolver):
    """Parks conflicting incoming ops in `pending` for user review.

    The runtime polls `pending` from the main thread and shows a UI
    popup. When the user resolves a conflict, they set the resolved
    Decision via `resolve_pending`. Non-conflicting ops fall back to
    LWW so the session keeps moving.
    """
    policy: ConflictPolicy = ConflictPolicy.MANUAL
    window_seconds: float = 2.0
    pending: list[tuple[str, ConflictContext]] = field(default_factory=list)
    _resolved: dict[str, ConflictDecision] = field(default_factory=dict)

    def decide(self, ctx: ConflictContext) -> ConflictDecision:
        if not _is_in_window(ctx, self.window_seconds):
            return ConflictDecision.APPLY if _lww_wins(ctx) else ConflictDecision.REJECT

        # If user already answered for this key, honor and clear.
        if ctx.key in self._resolved:
            return self._resolved.pop(ctx.key)

        # Park for UI. Avoid stacking duplicate keys.
        if not any(k == ctx.key for k, _ in self.pending):
            self.pending.append((ctx.key, ctx))
        return ConflictDecision.DEFER

    def resolve_pending(self, key: str, decision: ConflictDecision) -> None:
        self._resolved[key] = decision
        self.pending = [(k, c) for k, c in self.pending if k != key]

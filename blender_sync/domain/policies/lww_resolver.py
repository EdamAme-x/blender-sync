from __future__ import annotations


class LWWResolver:
    """Last-Write-Wins state cache.

    Stores the (seq, ts, author) of the most recently accepted update
    per key. Used both as the default conflict policy *and* as the
    accounting backbone for richer policies (which still need to know
    "what's the local state for this key right now").
    """

    def __init__(self) -> None:
        self._seen: dict[str, tuple[int, float, str]] = {}

    def should_apply(self, key: str, author: str, seq: int, ts: float) -> bool:
        cur = self._seen.get(key)
        if cur is None:
            self._seen[key] = (seq, ts, author)
            return True
        cur_seq, cur_ts, cur_author = cur
        incoming = (ts, seq, author)
        current = (cur_ts, cur_seq, cur_author)
        if incoming > current:
            self._seen[key] = (seq, ts, author)
            return True
        return False

    def get_state(
        self, key: str
    ) -> tuple[int, float, str] | None:
        """Return (seq, ts, author) of the last accepted update for `key`."""
        return self._seen.get(key)

    def force_record(
        self, key: str, author: str, seq: int, ts: float
    ) -> None:
        """Mark `key` as resolved at this point regardless of LWW order.
        Used by override policies (e.g. REMOTE_WINS) that bypass tuple
        comparison."""
        self._seen[key] = (seq, ts, author)

    def reset(self) -> None:
        self._seen.clear()

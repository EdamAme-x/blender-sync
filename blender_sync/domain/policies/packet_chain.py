"""Per-author packet chain checksum + gap detection.

Each peer maintains an outgoing rolling checksum updated on every reliable
packet it sends. Receivers track the same checksum per peer and detect
gaps by re-running the rolling update.

Algorithm (Adler-32-flavored, pure python, no external deps):

    a = 1
    b = 0
    For each reliable packet body bytes B:
        a = (a + sum(B)) mod MOD
        b = (b + a) mod MOD
    chain = (b << 16) | a

`MOD = 65521` is the largest prime under 2^16, giving a 32-bit checksum
with ~0.0015% collision probability on random corruption.

A single-digit "check digit" (chain mod 10) is also reported in the
packet header for readable debugging output ("…ch=37, dgt=4"). The full
32-bit value is what the receiver compares; the digit is purely UX.

Fast (unordered) channel packets are intentionally excluded from the
chain — by design transform updates may be dropped and we don't want
NACK storms over deliberately lossy frames.

Receiver behavior on mismatch:
  - Compare incoming `(seq, chain, digit)` against locally-rebuilt chain
    from the last verified seq.
  - If mismatch (or gap in seq), record the missing range and request
    RESEND via the control channel. Do not apply ops yet — wait for the
    re-sent packets to fill the chain back to the current seq.
  - After RESEND fills the gap, drain the held-back queue in seq order.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MOD = 65521


def step(a: int, b: int, body: bytes) -> tuple[int, int]:
    """Advance (a, b) by one packet body. Pure function — no globals."""
    s = sum(body) % MOD
    a = (a + s) % MOD
    b = (b + a) % MOD
    return a, b


def fold(a: int, b: int) -> int:
    return (b << 16) | a


def digit(chain: int) -> int:
    return chain % 10


@dataclass
class PacketChain:
    """Mutable rolling state shared per peer (one for outgoing, one per
    incoming author).

    Persists `(a, b, last_seq)`. On the sender side, every reliable packet
    advances the chain. On the receiver side, the chain is replayed using
    the body bytes of accepted packets.
    """
    a: int = 1
    b: int = 0
    last_seq: int = 0

    def advance(self, body: bytes) -> tuple[int, int]:
        self.a, self.b = step(self.a, self.b, body)
        return self.a, self.b

    @property
    def chain(self) -> int:
        return fold(self.a, self.b)

    @property
    def digit(self) -> int:
        return digit(self.chain)

    def reset(self) -> None:
        self.a = 1
        self.b = 0
        self.last_seq = 0


@dataclass
class PendingGap:
    """A range of missing seq numbers waiting for RESEND."""
    author: str
    first: int  # inclusive
    last: int   # inclusive

    def __contains__(self, seq: int) -> bool:
        return self.first <= seq <= self.last


@dataclass
class ReceiverChainState:
    """Receiver-side chain bookkeeping per author.

    `expected_seq` is the next seq the receiver wants. Anything > expected
    means a gap; anything <= last_verified_seq is a duplicate (probably a
    RESEND we already accepted).
    """
    chain: PacketChain = field(default_factory=PacketChain)
    expected_seq: int = 1
    last_verified_seq: int = 0
    pending_gap: PendingGap | None = None
    # Packets received out of order, keyed by seq, awaiting their predecessors.
    held_back: dict[int, bytes] = field(default_factory=dict)

    def is_duplicate(self, seq: int) -> bool:
        return seq <= self.last_verified_seq

    def is_gap(self, seq: int) -> bool:
        return seq > self.expected_seq

    def is_in_order(self, seq: int) -> bool:
        return seq == self.expected_seq

    def accept(self, seq: int, body: bytes) -> tuple[int, int]:
        """Mark seq as verified and advance the chain. Caller is
        responsible for ensuring this seq is in-order."""
        a, b = self.chain.advance(body)
        self.last_verified_seq = seq
        self.expected_seq = seq + 1
        return a, b

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EchoFilter:
    self_peer_id: str

    def should_accept(self, author: str) -> bool:
        return author != self.self_peer_id

from __future__ import annotations

from ...domain.entities import ChannelKind


def channel_options(kind: ChannelKind) -> dict:
    if kind is ChannelKind.RELIABLE:
        return {"ordered": True}
    return {"ordered": False, "maxRetransmits": 0}

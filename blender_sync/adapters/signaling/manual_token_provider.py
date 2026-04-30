from __future__ import annotations

import asyncio

from ...domain.entities import OfferPreparation, SessionStatus
from ...domain.errors import SignalingError
from ...domain.ports import ILogger, ISignalingProvider, ITokenCodec


class ManualTokenSignalingProvider(ISignalingProvider):
    name = "manual"

    def __init__(self, logger: ILogger) -> None:
        self._logger = logger
        self._answer_future: asyncio.Future[str] | None = None
        self._offer_future: asyncio.Future[str] | None = None

    async def prepare_offer(
        self, room_id: str, sdp: str, token_codec: ITokenCodec
    ) -> OfferPreparation:
        return OfferPreparation(
            share_token=token_codec.encode_manual(sdp),
            post_status=SessionStatus.AWAITING_MANUAL_ANSWER,
        )

    async def publish_offer(self, room_id: str, sdp: str) -> None:
        return

    async def wait_offer(self, room_id: str, timeout: float) -> str:
        loop = asyncio.get_running_loop()
        self._offer_future = loop.create_future()
        try:
            return await asyncio.wait_for(self._offer_future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SignalingError("manual offer wait timeout") from exc

    async def publish_answer(self, room_id: str, sdp: str) -> None:
        return

    async def wait_answer(self, room_id: str, timeout: float) -> str:
        loop = asyncio.get_running_loop()
        self._answer_future = loop.create_future()
        try:
            return await asyncio.wait_for(self._answer_future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SignalingError("manual answer wait timeout") from exc

    def submit_answer(self, sdp: str) -> None:
        if self._answer_future and not self._answer_future.done():
            self._answer_future.set_result(sdp)

    def submit_offer(self, sdp: str) -> None:
        if self._offer_future and not self._offer_future.done():
            self._offer_future.set_result(sdp)

    async def close(self) -> None:
        for fut in (self._answer_future, self._offer_future):
            if fut and not fut.done():
                fut.cancel()
        self._answer_future = None
        self._offer_future = None

from __future__ import annotations

from ...domain.entities import OfferPreparation
from ...domain.errors import SignalingError
from ...domain.ports import ILogger, ISignalingProvider, ITokenCodec


class SignalingPool(ISignalingProvider):
    name = "pool"

    def __init__(self, logger: ILogger, providers: list[ISignalingProvider]) -> None:
        self._logger = logger
        self._providers = providers

    async def prepare_offer(
        self, room_id: str, sdp: str, token_codec: ITokenCodec
    ) -> OfferPreparation:
        last: Exception | None = None
        for p in self._providers:
            try:
                return await p.prepare_offer(room_id, sdp, token_codec)
            except Exception as exc:
                last = exc
                self._logger.warning("prepare_offer via %s failed: %s", p.name, exc)
        raise SignalingError(str(last) if last else "no provider")

    async def publish_offer(self, room_id: str, sdp: str) -> None:
        last: Exception | None = None
        for p in self._providers:
            try:
                await p.publish_offer(room_id, sdp)
                return
            except Exception as exc:
                last = exc
                self._logger.warning("publish_offer via %s failed: %s", p.name, exc)
        if last:
            raise SignalingError(str(last))

    async def wait_offer(self, room_id: str, timeout: float) -> str:
        last: Exception | None = None
        for p in self._providers:
            try:
                return await p.wait_offer(room_id, timeout)
            except Exception as exc:
                last = exc
                self._logger.warning("wait_offer via %s failed: %s", p.name, exc)
        raise SignalingError(str(last) if last else "no provider")

    async def publish_answer(self, room_id: str, sdp: str) -> None:
        last: Exception | None = None
        for p in self._providers:
            try:
                await p.publish_answer(room_id, sdp)
                return
            except Exception as exc:
                last = exc
                self._logger.warning("publish_answer via %s failed: %s", p.name, exc)
        if last:
            raise SignalingError(str(last))

    async def wait_answer(self, room_id: str, timeout: float) -> str:
        last: Exception | None = None
        for p in self._providers:
            try:
                return await p.wait_answer(room_id, timeout)
            except Exception as exc:
                last = exc
                self._logger.warning("wait_answer via %s failed: %s", p.name, exc)
        raise SignalingError(str(last) if last else "no provider")

    async def close(self) -> None:
        for p in self._providers:
            try:
                await p.close()
            except Exception:
                pass

    @property
    def providers(self) -> list[ISignalingProvider]:
        return list(self._providers)

from __future__ import annotations

import secrets

from ..domain.entities import Session, SessionStatus, SyncConfig
from ..domain.errors import SignalingError, TransportError
from ..domain.ports import (
    IAsyncRunner,
    ILogger,
    ISessionEvents,
    ISignalingProvider,
    ITokenCodec,
    ITransport,
)


class StartSharingUseCase:
    def __init__(
        self,
        transport: ITransport,
        signaling_providers: list[ISignalingProvider],
        token_codec: ITokenCodec,
        logger: ILogger,
        events: ISessionEvents,
        async_runner: IAsyncRunner,
        config: SyncConfig,
    ) -> None:
        self._transport = transport
        self._providers = signaling_providers
        self._token_codec = token_codec
        self._logger = logger
        self._events = events
        self._async_runner = async_runner
        self._config = config

    def execute(self, session: Session) -> None:
        self._async_runner.run_coroutine(self._execute_async(session))

    async def _execute_async(self, session: Session) -> None:
        session.status = SessionStatus.SHARING
        self._events.on_status(session.status.value)
        self._transport.configure(self._config.transport.ice_servers)

        room_id = secrets.token_urlsafe(12)
        session.room_id = room_id

        try:
            offer_sdp = await self._transport.create_offer()
        except Exception as exc:
            session.status = SessionStatus.ERROR
            session.error = f"create_offer failed: {exc}"
            self._events.on_error(session.error)
            raise TransportError(session.error) from exc

        await self._transport.gather_complete(timeout=8.0)
        full_offer = self._transport.local_description() or offer_sdp

        for provider in self._providers:
            try:
                preparation = await provider.prepare_offer(
                    room_id, full_offer, self._token_codec
                )
                session.token = preparation.share_token
                session.status = preparation.post_status
                self._events.on_status(session.status.value)
                self._logger.info(
                    "offer ready via %s, status=%s, token len=%d",
                    provider.name, session.status.value,
                    len(preparation.share_token),
                )
                # Wait for the answer. The timeout depends on which transport
                # we ended up using: relay-mediated (nostr) is fast; manual
                # is bounded by user copy-paste latency.
                if session.status is SessionStatus.AWAITING_MANUAL_ANSWER:
                    timeout = self._config.signaling.answer_timeout_seconds
                else:
                    timeout = self._config.signaling.nostr_timeout_seconds
                answer_sdp = await provider.wait_answer(room_id, timeout=timeout)
                await self._transport.accept_answer(answer_sdp)
                session.status = SessionStatus.LIVE
                self._events.on_status(session.status.value)
                return
            except Exception as exc:
                self._logger.warning("signaling %s failed: %s", provider.name, exc)
                continue

        session.status = SessionStatus.ERROR
        session.error = "All signaling providers failed"
        self._events.on_error(session.error)
        raise SignalingError(session.error)

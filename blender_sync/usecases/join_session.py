from __future__ import annotations

from ..domain.entities import Session, SessionStatus, SyncConfig
from ..domain.errors import SignalingError, TokenParseError, TransportError
from ..domain.ports import (
    IAsyncRunner,
    ILogger,
    ISessionEvents,
    ISignalingProvider,
    ITokenCodec,
    ITransport,
)


class JoinSessionUseCase:
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

    def execute(self, session: Session, token: str) -> None:
        self._async_runner.run_coroutine(self._execute_async(session, token))

    async def _execute_async(self, session: Session, token: str) -> None:
        session.status = SessionStatus.CONNECTING
        self._events.on_status(session.status.value)
        self._transport.configure(self._config.transport.ice_servers)

        is_short = self._token_codec.is_short(token)
        is_manual = False
        try:
            if is_short:
                room_id, _hmac = self._token_codec.decode_short(token)
                session.room_id = room_id
                provider = self._pick_provider("nostr")
                offer_sdp = await provider.wait_offer(
                    room_id, timeout=self._config.signaling.answer_timeout_seconds
                )
            else:
                offer_sdp = self._token_codec.decode_manual(token)
                provider = self._pick_provider("manual")
                is_manual = True
        except TokenParseError as exc:
            session.status = SessionStatus.ERROR
            session.error = f"invalid token: {exc}"
            self._events.on_error(session.error)
            raise

        try:
            answer_sdp = await self._transport.create_answer(offer_sdp)
        except Exception as exc:
            session.status = SessionStatus.ERROR
            session.error = f"create_answer failed: {exc}"
            self._events.on_error(session.error)
            raise TransportError(session.error) from exc

        await self._transport.gather_complete(timeout=8.0)
        full_answer = self._transport.local_description() or answer_sdp

        if is_manual:
            # Manual route: encode answer SDP back into a token for the user
            # to copy and send to the offerer. Don't publish to a relay
            # (the manual provider's publish_answer is a no-op anyway).
            answer_token = self._token_codec.encode_manual(full_answer)
            session.token = answer_token
            session.status = SessionStatus.AWAITING_MANUAL_ANSWER
            self._events.on_status(session.status.value)
            self._logger.info(
                "manual answer token ready (%d chars) — share with offerer",
                len(answer_token),
            )
            return

        try:
            await provider.publish_answer(session.room_id or "", full_answer)
        except Exception as exc:
            session.status = SessionStatus.ERROR
            session.error = f"publish_answer failed: {exc}"
            self._events.on_error(session.error)
            raise SignalingError(session.error) from exc

        session.status = SessionStatus.LIVE
        self._events.on_status(session.status.value)

    def _pick_provider(self, name: str) -> ISignalingProvider:
        for p in self._providers:
            if p.name == name:
                return p
        raise SignalingError(f"signaling provider '{name}' not registered")

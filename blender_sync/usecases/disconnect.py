from __future__ import annotations

from ..domain.entities import Session, SessionStatus
from ..domain.ports import (
    IAsyncRunner,
    ILogger,
    ISessionEvents,
    ISignalingProvider,
    ITransport,
)


class DisconnectUseCase:
    def __init__(
        self,
        transport: ITransport,
        signaling_providers: list[ISignalingProvider],
        logger: ILogger,
        events: ISessionEvents,
        async_runner: IAsyncRunner,
    ) -> None:
        self._transport = transport
        self._providers = signaling_providers
        self._logger = logger
        self._events = events
        self._async_runner = async_runner

    def execute(self, session: Session) -> None:
        self._async_runner.run_coroutine(self._execute_async(session))

    def execute_blocking(self, session: Session, timeout: float = 5.0) -> None:
        try:
            self._async_runner.run_coroutine_blocking(
                self._execute_async(session), timeout=timeout
            )
        except Exception as exc:
            self._logger.warning("disconnect blocking failed: %s", exc)

    async def _execute_async(self, session: Session) -> None:
        for provider in self._providers:
            try:
                await provider.close()
            except Exception as exc:
                self._logger.warning("provider %s close failed: %s", provider.name, exc)

        try:
            await self._transport.close()
        except Exception as exc:
            self._logger.warning("transport close failed: %s", exc)

        session.status = SessionStatus.IDLE
        session.token = None
        session.room_id = None
        session.remote_peers.clear()
        session.error = None
        self._events.on_status(session.status.value)
        try:
            self._events.on_disconnected()
        except Exception as exc:
            self._logger.warning("on_disconnected handler failed: %s", exc)

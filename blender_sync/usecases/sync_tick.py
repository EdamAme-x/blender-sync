from __future__ import annotations

from ..domain.entities import CategoryKind, Session, SessionStatus, SyncConfig
from ..domain.policies.packet_builder import OutboundHistory, PacketBuilder
from ..domain.ports import (
    IAsyncRunner,
    IClock,
    ICodec,
    ILogger,
    ISceneDirtyCollector,
    ITransport,
)


class SyncTickUseCase:
    def __init__(
        self,
        scene: ISceneDirtyCollector,
        transport: ITransport,
        codec: ICodec,
        clock: IClock,
        logger: ILogger,
        async_runner: IAsyncRunner,
        builder: PacketBuilder,
        config: SyncConfig,
        history: OutboundHistory | None = None,
    ) -> None:
        self._scene = scene
        self._transport = transport
        self._codec = codec
        self._clock = clock
        self._logger = logger
        self._async_runner = async_runner
        self._builder = builder
        self._config = config
        self._history = history

    def tick(self, session: Session) -> None:
        if session.status is not SessionStatus.LIVE:
            return
        if self._scene.is_applying_remote():
            return

        enabled = self._enabled_categories()
        if not enabled:
            return

        try:
            grouped = self._scene.collect_dirty_ops(enabled)
        except Exception as exc:
            self._logger.error("collect_dirty_ops failed: %s", exc)
            return

        if not grouped:
            return

        ts = self._clock.now()
        for category, ops in grouped:
            if not ops:
                continue
            packet = self._builder.build(category, ops, ts)
            try:
                data = self._codec.encode(packet)
            except Exception as exc:
                self._logger.error("codec.encode failed for %s: %s", category, exc)
                continue
            if self._history is not None:
                self._history.record(packet)
            self._async_runner.run_coroutine(
                self._transport.send(packet.channel, data)
            )

    def _enabled_categories(self) -> list[CategoryKind]:
        return list(self._config.filters.enabled_categories())

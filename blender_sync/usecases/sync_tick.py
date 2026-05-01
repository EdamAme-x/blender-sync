from __future__ import annotations

from ..domain.entities import (
    CATEGORY_TO_CHANNEL, CategoryKind, ChannelKind,
    Session, SessionStatus, SyncConfig,
)
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

        # If the local user just pressed Ctrl+Z / Ctrl+Shift+Z, the
        # gateway raised an undo flag and pre-marked every category
        # dirty. Build this batch as force=True so peers accept the
        # rewound state instead of rejecting it via LWW (their last
        # seen ts is newer than the post-undo state).
        force_this_tick = False
        try:
            force_this_tick = bool(self._scene.consume_undo_pending_force())
        except Exception as exc:
            self._logger.debug(
                "consume_undo_pending_force unavailable: %s", exc,
            )

        ts = self._clock.now()
        for category, ops in grouped:
            if not ops:
                continue
            # Force flag is only meaningful on RELIABLE-channel
            # categories. FAST-channel ops (transform / pose / view3d)
            # ride the unordered+lossy lane with chain==0; they have no
            # ordering guarantee, so a force-flagged FAST packet that
            # arrives late would bypass LWW and silently rewind the
            # peer to the older state. Strip force on those categories
            # — the next normal FAST packet from the new local state
            # will overwrite peers in the right direction.
            packet_force = force_this_tick and (
                CATEGORY_TO_CHANNEL.get(category) is ChannelKind.RELIABLE
            )
            packet = self._builder.build(
                category, ops, ts, force=packet_force,
            )
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
        if force_this_tick:
            self._logger.info(
                "broadcasted post-undo state as %d force packets",
                len(grouped),
            )

    def _enabled_categories(self) -> list[CategoryKind]:
        return list(self._config.filters.enabled_categories())

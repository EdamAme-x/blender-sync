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

        # Consume the undo flag BEFORE the empty-batch early return.
        # If we returned early without consuming it, an undo whose
        # categories happen to be all filtered off (or whose ops were
        # absorbed by hash dedupe) would leave the flag set, and the
        # next unrelated reliable edit would go out as force=True,
        # silently overwriting newer peer state.
        force_this_tick = False
        try:
            force_this_tick = bool(self._scene.consume_undo_pending_force())
        except Exception as exc:
            self._logger.debug(
                "consume_undo_pending_force unavailable: %s", exc,
            )

        if not grouped:
            return

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

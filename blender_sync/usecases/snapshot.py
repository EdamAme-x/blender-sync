from __future__ import annotations

from ..domain.entities import CategoryKind, SyncConfig
from ..domain.policies.packet_builder import PacketBuilder
from ..domain.ports import (
    IAsyncRunner,
    IClock,
    ICodec,
    ILogger,
    ISceneSnapshot,
    ITransport,
)


class SnapshotUseCase:
    def __init__(
        self,
        scene: ISceneSnapshot,
        transport: ITransport,
        codec: ICodec,
        clock: IClock,
        logger: ILogger,
        async_runner: IAsyncRunner,
        builder: PacketBuilder,
        config: SyncConfig,
    ) -> None:
        self._scene = scene
        self._transport = transport
        self._codec = codec
        self._clock = clock
        self._logger = logger
        self._async_runner = async_runner
        self._builder = builder
        self._config = config

    def send_initial(self) -> None:
        try:
            grouped = self._scene.build_full_snapshot(initial_snapshot=True)
        except Exception as exc:
            self._logger.error("build_full_snapshot failed: %s", exc)
            return

        ts = self._clock.now()
        merged_ops: list[dict] = []
        for category, ops in grouped:
            for op in ops:
                merged_ops.append({"category": category.value, "op": op})

        if not merged_ops:
            return

        packet = self._builder.build(CategoryKind.SNAPSHOT, merged_ops, ts)
        data = self._codec.encode(packet)
        self._async_runner.run_coroutine(
            self._transport.send(packet.channel, data)
        )

    def apply_received(self, packet_ops: list[dict]) -> None:
        from collections import defaultdict

        regrouped: dict[CategoryKind, list[dict]] = defaultdict(list)
        for entry in packet_ops:
            try:
                cat = CategoryKind(entry["category"])
            except (KeyError, ValueError):
                continue
            regrouped[cat].append(entry["op"])

        self._scene.set_applying_remote(True)
        try:
            for cat, ops in regrouped.items():
                self._scene.apply_ops(cat, ops)
        except Exception as exc:
            self._logger.error("snapshot apply failed: %s", exc)
        finally:
            self._scene.set_applying_remote(False)

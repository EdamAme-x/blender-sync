"""Composition Root for Blender Sync.

Wires every Adapter implementation behind a domain Port and injects them
into UseCases. Owns the asyncio loop lifecycle and the per-tick drain of
inbound packets and outbound dirty ops.

Responsibilities of this module:
  1. DI wiring (constructor)
  2. tick loop + start/stop
  3. UseCase facade for the UI layer

UI ↔ bpy state is delegated to ``presentation/state_sync.py``.
"""
from __future__ import annotations

from typing import Any

from .adapters.clock.system_clock import SystemClock
from .adapters.codec.msgpack_zstd_codec import MsgpackZstdCodec
from .adapters.codec.token_codec import Base58TokenCodec
from .adapters.logger.stdout_logger import StdoutLogger
from .adapters.scene.bpy_scene_gateway import BpySceneGateway
from .adapters.scheduler.bpy_timer_scheduler import BpyTimerScheduler
from .adapters.signaling.manual_token_provider import ManualTokenSignalingProvider
from .adapters.signaling.nostr_provider import NostrSignalingProvider
from .adapters.signaling.signaling_pool import SignalingPool
from .adapters.transport.aiortc_transport import AiortcTransport
from .domain.entities import (
    ChannelKind,
    Peer,
    Session,
    SignalingConfig,
    SyncConfig,
)
from .domain.policies.conflict_resolver import (
    AutoLWWResolver,
    ConflictPolicy,
    IConflictResolver,
    LocalWinsResolver,
    ManualResolver,
    PeerPriorityResolver,
    RemoteWinsResolver,
)
from .domain.policies.dirty_tracker import DirtyTracker
from .domain.policies.echo_filter import EchoFilter
from .domain.policies.lww_resolver import LWWResolver
from .domain.policies.packet_builder import (
    OutboundHistory,
    PacketBuilder,
    SeqCounter,
)
from .domain.ports import ISignalingProvider
from .infrastructure.async_loop import AsyncioBackgroundRunner
from .infrastructure.thread_bridge import ThreadSafeQueue
from .presentation.state_sync import BpyConfigReader, BpyStateSync
from .usecases.apply_remote import ApplyRemotePacketUseCase
from .usecases.disconnect import DisconnectUseCase
from .usecases.force_sync import (
    ControlMessageHandler,
    ForcePullUseCase,
    ForcePushUseCase,
)
from .usecases.join_session import JoinSessionUseCase
from .usecases.snapshot import SnapshotUseCase
from .usecases.start_sharing import StartSharingUseCase
from .usecases.sync_tick import SyncTickUseCase


class SyncRuntime:
    """Composition root + tick loop.

    The constructor is the only place that instantiates concrete Adapters.
    UseCases receive only Domain ports.
    """

    def __init__(self) -> None:
        self.logger = StdoutLogger()
        self.async_runner = AsyncioBackgroundRunner(self.logger)
        self.scheduler = BpyTimerScheduler()

        self.clock = SystemClock()
        self.codec = MsgpackZstdCodec()
        self.token_codec = Base58TokenCodec()

        peer_id = self._make_peer_id()
        self.config = SyncConfig(peer_id=peer_id)
        self.session = Session(local_peer=Peer(peer_id=peer_id))

        self.dirty = DirtyTracker()
        self.echo = EchoFilter(self_peer_id=peer_id)
        self.lww = LWWResolver()
        self.conflict_resolver: IConflictResolver = AutoLWWResolver()
        self.seq = SeqCounter()
        self.packet_builder = PacketBuilder(peer_id=peer_id, seq=self.seq)
        self.outbound_history = OutboundHistory(capacity=512)

        self.transport = AiortcTransport(self.logger)
        self.manual_provider = ManualTokenSignalingProvider(self.logger)
        self.nostr_provider: NostrSignalingProvider = NostrSignalingProvider(
            self.logger, self.config.signaling.nostr_relays
        )
        self._providers: list[ISignalingProvider] = [
            self.nostr_provider, self.manual_provider
        ]
        self.signaling_pool = SignalingPool(self.logger, self._providers)

        self.scene = BpySceneGateway(self.logger, self.dirty)

        self.inbound = ThreadSafeQueue[bytes]()
        self.main_thread_calls = ThreadSafeQueue[Any]()

        # Presentation-layer helpers — separated from the runtime per SRP.
        self.events = BpyStateSync(self.main_thread_calls.put, self.logger)
        self.config_reader = BpyConfigReader()

        self.uc_start = StartSharingUseCase(
            self.transport, self._providers, self.token_codec,
            self.logger, self.events, self.async_runner, self.config,
        )
        self.uc_join = JoinSessionUseCase(
            self.transport, self._providers, self.token_codec,
            self.logger, self.events, self.async_runner, self.config,
        )
        self.uc_disconnect = DisconnectUseCase(
            self.transport, self._providers, self.logger,
            self.events, self.async_runner,
        )
        self.uc_sync_tick = SyncTickUseCase(
            self.scene, self.transport, self.codec, self.clock,
            self.logger, self.async_runner, self.packet_builder, self.config,
            history=self.outbound_history,
        )
        self.uc_apply = ApplyRemotePacketUseCase(
            self.scene, self.codec, self.echo, self.lww, self.logger, self.config,
            conflict_resolver=self.conflict_resolver,
            clock=self.clock,
        )
        self.uc_snapshot = SnapshotUseCase(
            self.scene, self.transport, self.codec, self.clock,
            self.logger, self.async_runner, self.packet_builder, self.config,
        )
        self.uc_force_push = ForcePushUseCase(
            self.scene, self.transport, self.codec, self.clock,
            self.logger, self.async_runner, self.packet_builder, self.config,
            history=self.outbound_history,
        )
        self.uc_force_pull = ForcePullUseCase(
            self.transport, self.codec, self.clock,
            self.logger, self.async_runner, self.packet_builder, self.config,
        )
        self.control_handler = ControlMessageHandler(
            self.uc_force_push, self.transport, self.codec, self.clock,
            self.logger, self.async_runner, self.packet_builder,
            history=self.outbound_history,
        )
        self.control_handler.set_latency_listener(self._on_latency_ms)
        self.control_handler.set_resend_receiver(self.inbound.put)
        self.uc_apply.set_control_handler(self.session, self.control_handler.handle)
        self.uc_apply.set_nack_emitter(self._emit_nack)

        self._bytes_in = 0
        self._bytes_out = 0
        self._last_metric_at = self.clock.monotonic()
        self._last_ping_at = 0.0
        self._latest_latency_ms = 0.0

        self.transport.on_recv(self._on_recv_from_async)

    def _make_peer_id(self) -> str:
        import uuid
        return f"peer_{uuid.uuid4().hex[:8]}"

    def _on_recv_from_async(self, channel: ChannelKind, data: bytes) -> None:
        self._bytes_in += len(data)
        self.inbound.put(data)

    def _on_latency_ms(self, ms: float) -> None:
        self._latest_latency_ms = ms

    def _emit_nack(self, author: str, first: int, last: int) -> None:
        try:
            self.control_handler.send_nack(author, first, last)
        except Exception as exc:
            self.logger.warning("send_nack failed: %s", exc)

    def _flush_metrics(self) -> None:
        now = self.clock.monotonic()
        elapsed = now - self._last_metric_at
        if elapsed < 1.0:
            return
        kbps = (self._bytes_in + self._bytes_out) / 1024.0 / elapsed
        self._bytes_in = 0
        self._bytes_out = 0
        self._last_metric_at = now
        peer_count = 1 if self.session.status.value == "live" else 0
        self.events.queue_status_update(
            latency_ms=self._latest_latency_ms,
            bandwidth_kbps=kbps,
            peer_count=peer_count,
        )

        if self.session.status.value == "live" and (now - self._last_ping_at) > 2.0:
            self._last_ping_at = now
            try:
                self.control_handler.send_ping()
            except Exception:
                pass

    # --- Provider hot-swap (Preferences updates) -----------------------

    def _resolver_for(self, policy: ConflictPolicy, window: float,
                      priority: tuple[str, ...]) -> IConflictResolver:
        if policy is ConflictPolicy.LOCAL_WINS:
            return LocalWinsResolver(window_seconds=window)
        if policy is ConflictPolicy.REMOTE_WINS:
            return RemoteWinsResolver(window_seconds=window)
        if policy is ConflictPolicy.PEER_PRIORITY:
            return PeerPriorityResolver(
                priority_order=priority, window_seconds=window,
            )
        if policy is ConflictPolicy.MANUAL:
            return ManualResolver(window_seconds=window)
        return AutoLWWResolver()

    def set_conflict_policy(
        self, policy: ConflictPolicy, window: float = 2.0,
        priority: tuple[str, ...] = (),
    ) -> None:
        self.conflict_resolver = self._resolver_for(policy, window, priority)
        self.uc_apply.set_conflict_resolver(self.conflict_resolver)

    def _swap_nostr_provider(self, new_provider: NostrSignalingProvider) -> None:
        old = self.nostr_provider
        self.nostr_provider = new_provider
        for i, p in enumerate(self._providers):
            if p is old:
                self._providers[i] = new_provider
                break
        try:
            self.async_runner.run_coroutine(old.close())
        except Exception as exc:
            self.logger.warning("old nostr close failed: %s", exc)

    def _refresh_from_bpy(self) -> None:
        """Re-read Sync Filters and Preferences from bpy state. Idempotent."""
        filters = self.config_reader.read_filters()
        if filters is not None:
            self.config.filters = filters

        transport_cfg = self.config_reader.read_transport_config()
        if transport_cfg is not None:
            self.config.transport = transport_cfg

        relays = self.config_reader.read_signaling_relays()
        if relays is not None and relays != self.config.signaling.nostr_relays:
            self.config.signaling = SignalingConfig(nostr_relays=relays)
            self._swap_nostr_provider(NostrSignalingProvider(self.logger, relays))

        conflict_cfg = self.config_reader.read_conflict_config()
        if conflict_cfg is not None:
            self.config.conflict = conflict_cfg
            try:
                policy = ConflictPolicy(conflict_cfg.policy)
            except ValueError:
                policy = ConflictPolicy.AUTO_LWW
            self.set_conflict_policy(
                policy,
                window=conflict_cfg.window_seconds,
                priority=conflict_cfg.peer_priority,
            )

    # --- Lifecycle -----------------------------------------------------

    def start(self) -> None:
        self.async_runner.start()
        self.scene.install_change_listeners()
        self.scheduler.schedule(self._tick, self.config.tick_interval_seconds)

    def stop(self) -> None:
        self.scheduler.cancel(self._tick)
        self.scene.uninstall_change_listeners()
        try:
            self.uc_disconnect.execute_blocking(self.session, timeout=5.0)
        except Exception as exc:
            self.logger.warning("disconnect on stop failed: %s", exc)
        self.async_runner.stop()

    def _tick(self) -> None:
        for fn in self.main_thread_calls.drain(50):
            try:
                fn()
            except Exception as exc:
                self.logger.error("main-thread call failed: %s", exc)

        for data in self.inbound.drain(self.config.inbound_max_per_tick):
            self.uc_apply.apply_raw(data)

        self.uc_sync_tick.tick(self.session)
        self._flush_metrics()

    # --- Facade for UI Operators --------------------------------------

    def start_sharing(self) -> None:
        self._refresh_from_bpy()
        self.uc_start.execute(self.session)

    def join_session(self, token: str) -> None:
        self._refresh_from_bpy()
        self.uc_join.execute(self.session, token)

    def disconnect(self) -> None:
        self.uc_disconnect.execute(self.session)

    def submit_manual_answer(self, token: str) -> None:
        sdp = self.token_codec.decode_manual(token)
        self.async_runner.call_soon(self.manual_provider.submit_answer, sdp)

    def force_push(self) -> None:
        self._refresh_from_bpy()
        self.uc_force_push.execute(self.session)

    def force_pull(self) -> None:
        self._refresh_from_bpy()
        self.uc_force_pull.execute(self.session)


runtime: SyncRuntime | None = None


def init() -> SyncRuntime:
    global runtime
    if runtime is None:
        runtime = SyncRuntime()
        runtime.start()
    return runtime


def shutdown() -> None:
    global runtime
    if runtime is not None:
        try:
            runtime.stop()
        except Exception:
            pass
        runtime = None

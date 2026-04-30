from __future__ import annotations

import asyncio
from typing import Any

from ...domain.entities import ChannelKind, IceServer
from ...domain.errors import TransportError
from ...domain.ports import (
    ILogger,
    ITransport,
    RecvCallback,
    StateChangeCallback,
)
from .channel_kind import channel_options


class AiortcTransport(ITransport):
    def __init__(self, logger: ILogger) -> None:
        self._logger = logger
        self._pc: Any = None
        self._channels: dict[ChannelKind, Any] = {}
        self._ice_servers: tuple[IceServer, ...] = ()
        self._recv_cb: RecvCallback | None = None
        self._state_cb: StateChangeCallback | None = None
        self._gather_event: asyncio.Event | None = None

    def configure(self, ice_servers: tuple[IceServer, ...]) -> None:
        self._ice_servers = ice_servers

    def _ensure_pc(self) -> Any:
        if self._pc is not None:
            return self._pc
        try:
            from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
        except ImportError as exc:
            raise TransportError(
                "aiortc is not installed. Bundle the wheel via blender_manifest.toml."
            ) from exc

        ice = []
        for s in self._ice_servers:
            kwargs: dict[str, Any] = {"urls": s.url}
            if s.username:
                kwargs["username"] = s.username
            if s.credential:
                kwargs["credential"] = s.credential
            ice.append(RTCIceServer(**kwargs))

        config = RTCConfiguration(iceServers=ice or None)
        self._pc = RTCPeerConnection(configuration=config)
        self._gather_event = asyncio.Event()

        @self._pc.on("connectionstatechange")
        async def _on_state():
            state = self._pc.connectionState
            self._logger.info("pc connectionState=%s", state)
            if self._state_cb:
                self._state_cb(state)

        @self._pc.on("icegatheringstatechange")
        async def _on_gather():
            if self._pc.iceGatheringState == "complete" and self._gather_event:
                self._gather_event.set()

        @self._pc.on("datachannel")
        def _on_datachannel(channel):
            self._attach_channel(channel)

        return self._pc

    def _attach_channel(self, channel: Any) -> None:
        label = channel.label
        try:
            kind = ChannelKind(label)
        except ValueError:
            self._logger.warning("unknown datachannel label: %s", label)
            return
        self._channels[kind] = channel

        @channel.on("message")
        def _on_message(message):
            if isinstance(message, str):
                data = message.encode("utf-8")
            else:
                data = bytes(message)
            if self._recv_cb is not None:
                try:
                    self._recv_cb(kind, data)
                except Exception as exc:
                    self._logger.error("recv callback failed: %s", exc)

    async def create_offer(self) -> str:
        pc = self._ensure_pc()
        for kind in (ChannelKind.RELIABLE, ChannelKind.FAST):
            opts = channel_options(kind)
            channel = pc.createDataChannel(kind.value, **opts)
            self._attach_channel(channel)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        return pc.localDescription.sdp

    async def create_answer(self, offer_sdp: str) -> str:
        from aiortc import RTCSessionDescription

        pc = self._ensure_pc()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return pc.localDescription.sdp

    async def accept_answer(self, answer_sdp: str) -> None:
        from aiortc import RTCSessionDescription

        pc = self._ensure_pc()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))

    async def gather_complete(self, timeout: float) -> None:
        if self._pc is None or self._gather_event is None:
            return
        if self._pc.iceGatheringState == "complete":
            return
        try:
            await asyncio.wait_for(self._gather_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._logger.warning("ICE gather timeout after %.1fs", timeout)

    def local_description(self) -> str | None:
        if self._pc is None or self._pc.localDescription is None:
            return None
        return self._pc.localDescription.sdp

    async def send(self, channel: ChannelKind, data: bytes) -> None:
        ch = self._channels.get(channel)
        if ch is None:
            self._logger.warning("channel %s not open; drop %d bytes", channel, len(data))
            return
        if ch.readyState != "open":
            self._logger.debug("channel %s not ready (%s); drop", channel, ch.readyState)
            return
        ch.send(data)

    def on_recv(self, callback: RecvCallback) -> None:
        self._recv_cb = callback

    def on_state_change(self, callback: StateChangeCallback) -> None:
        self._state_cb = callback

    async def close(self) -> None:
        if self._pc is None:
            return
        try:
            await self._pc.close()
        except Exception as exc:
            self._logger.warning("pc close error: %s", exc)
        self._pc = None
        self._channels.clear()
        self._gather_event = None

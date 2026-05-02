"""Nostr signaling provider.

Uses Nostr ephemeral events (kind 25001/25002, parameterized by 'd' tag = room
id) to exchange WebRTC SDP offers/answers between two peers. Events are
properly signed with Schnorr (secp256k1) per NIP-01.

Each session creates an ephemeral identity (random secret key) used solely for
signaling — no persistent identity is leaked to relays.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any

from ...domain.entities import OfferPreparation, SessionStatus
from ...domain.errors import SignalingError
from ...domain.ports import ILogger, ISignalingProvider, ITokenCodec

# NIP-33 parameterized replaceable events (30000-39999) — relays persist
# the latest event per (pubkey, kind, d-tag), so a peer that subscribes
# AFTER the offer was published can still receive it. Ephemeral events
# (20000-29999) would be dropped immediately and miss late subscribers.
NOSTR_KIND_OFFER = 30078
NOSTR_KIND_ANSWER = 30079


class _SignerUnavailable(Exception):
    pass


def _load_signer():
    """Returns a callable (secret_hex, message_bytes) -> sig_hex
    and a callable secret_to_xonly_pubkey(secret_hex) -> hex.
    Raises _SignerUnavailable if coincurve is not installed."""
    try:
        from coincurve import PrivateKey
    except ImportError as exc:
        raise _SignerUnavailable(
            "coincurve wheel is required for Nostr signing"
        ) from exc

    def sign(secret_hex: str, msg32: bytes) -> str:
        sk = PrivateKey(bytes.fromhex(secret_hex))
        sig = sk.sign_schnorr(msg32)
        return sig.hex()

    def xonly_pubkey(secret_hex: str) -> str:
        sk = PrivateKey(bytes.fromhex(secret_hex))
        pk = sk.public_key.format(compressed=True)
        return pk[1:].hex()

    return sign, xonly_pubkey


def _new_secret_hex() -> str:
    return os.urandom(32).hex()


def _build_event(
    secret_hex: str,
    pubkey_hex: str,
    kind: int,
    tags: list[list[str]],
    content: str,
    sign,
) -> dict[str, Any]:
    created_at = int(time.time())
    serialized = json.dumps(
        [0, pubkey_hex, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    sig = sign(secret_hex, bytes.fromhex(event_id))
    return {
        "id": event_id,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


class NostrSignalingProvider(ISignalingProvider):
    name = "nostr"

    def __init__(self, logger: ILogger, relays: tuple[str, ...]) -> None:
        self._logger = logger
        self._relays = relays
        self._connections: list[Any] = []
        # Pending `_wait` calls subscribe to this list of futures so a
        # `close()` (e.g. user pressed Disconnect) can wake them up
        # instead of leaving them blocked on the full timeout. Without
        # this the user-visible Disconnect button is a no-op while the
        # 180s nostr wait is still ticking.
        self._pending_waits: list[asyncio.Future[str]] = []
        self._secret_hex = _new_secret_hex()
        try:
            self._sign, self._xonly = _load_signer()
            self._pubkey_hex = self._xonly(self._secret_hex)
            self._signer_ready = True
        except _SignerUnavailable as exc:
            self._signer_ready = False
            self._logger.warning("nostr signer unavailable: %s", exc)

    async def _connect_all(self) -> list[Any]:
        try:
            import websockets
        except ImportError as exc:
            raise SignalingError(
                "websockets is not installed. Bundle the wheel via blender_manifest.toml."
            ) from exc

        if self._connections:
            return self._connections

        async def connect(url: str):
            try:
                ws = await asyncio.wait_for(websockets.connect(url), timeout=5.0)
                return ws
            except Exception as exc:
                self._logger.warning("nostr relay %s connect failed: %s", url, exc)
                return None

        results = await asyncio.gather(*(connect(u) for u in self._relays))
        self._connections = [c for c in results if c is not None]
        if not self._connections:
            raise SignalingError("no nostr relay reachable")
        return self._connections

    async def _publish(self, room_id: str, sdp: str, kind: int) -> None:
        if not self._signer_ready:
            raise SignalingError("nostr signer (coincurve) not available")
        conns = await self._connect_all()
        event = _build_event(
            self._secret_hex, self._pubkey_hex, kind,
            [["d", room_id]], sdp, self._sign,
        )
        msg = json.dumps(["EVENT", event])
        results = await asyncio.gather(
            *(self._safe_send(c, msg) for c in conns), return_exceptions=True
        )
        successful = sum(1 for r in results if r is True)
        self._logger.info("nostr publish kind=%d to %d/%d relays", kind, successful, len(conns))

    async def _safe_send(self, ws: Any, msg: str) -> bool:
        try:
            await ws.send(msg)
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                self._logger.debug("relay ack: %s", resp[:120])
            except asyncio.TimeoutError:
                pass
            return True
        except Exception as exc:
            self._logger.warning("nostr send failed: %s", exc)
            return False

    async def _wait(self, room_id: str, kind: int, timeout: float) -> str:
        conns = await self._connect_all()
        sub_id = f"sub-{room_id}-{kind}"
        req = json.dumps([
            "REQ", sub_id,
            {"kinds": [kind], "#d": [room_id], "limit": 10},
        ])

        done: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        # Register so close() can cancel us early.
        self._pending_waits.append(done)

        async def watch(ws: Any) -> None:
            try:
                await ws.send(req)
                async for raw in ws:
                    if done.done():
                        return
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(msg, list) or len(msg) < 2:
                        continue
                    op = msg[0]
                    if op == "NOTICE":
                        self._logger.debug("relay NOTICE: %s", msg[1] if len(msg) > 1 else "")
                        continue
                    if op != "EVENT" or len(msg) < 3:
                        continue
                    event = msg[2] if isinstance(msg[2], dict) else None
                    if not event:
                        continue
                    if event.get("pubkey") == self._pubkey_hex:
                        continue
                    sdp = event.get("content")
                    if isinstance(sdp, str) and sdp:
                        if not done.done():
                            done.set_result(sdp)
                        return
            except Exception as exc:
                self._logger.debug("nostr watch error: %s", exc)

        watchers = [asyncio.create_task(watch(c)) for c in conns]
        try:
            return await asyncio.wait_for(done, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SignalingError(f"nostr wait timeout (kind={kind})") from exc
        except asyncio.CancelledError:
            # close() cancelled the future. Surface as SignalingError
            # so the caller (StartSharingUseCase / JoinSessionUseCase)
            # treats it like a regular failure and the runtime stops
            # waiting.
            raise SignalingError(f"nostr wait cancelled (kind={kind})")
        finally:
            for t in watchers:
                t.cancel()
            try:
                self._pending_waits.remove(done)
            except ValueError:
                pass

    async def prepare_offer(
        self, room_id: str, sdp: str, token_codec: ITokenCodec
    ) -> OfferPreparation:
        await self._publish(room_id, sdp, NOSTR_KIND_OFFER)
        return OfferPreparation(
            share_token=token_codec.encode_short(room_id, ""),
            post_status=SessionStatus.AWAITING_ANSWER,
        )

    async def publish_offer(self, room_id: str, sdp: str) -> None:
        await self._publish(room_id, sdp, NOSTR_KIND_OFFER)

    async def wait_offer(self, room_id: str, timeout: float) -> str:
        return await self._wait(room_id, NOSTR_KIND_OFFER, timeout)

    async def publish_answer(self, room_id: str, sdp: str) -> None:
        await self._publish(room_id, sdp, NOSTR_KIND_ANSWER)

    async def wait_answer(self, room_id: str, timeout: float) -> str:
        return await self._wait(room_id, NOSTR_KIND_ANSWER, timeout)

    async def close(self) -> None:
        # Wake up every in-flight _wait() so the runtime doesn't sit
        # idle until its 180s timeout fires. The wait_for layer
        # propagates cancellation as CancelledError, which _wait
        # converts into a SignalingError for the caller.
        for fut in list(self._pending_waits):
            if not fut.done():
                fut.cancel()
        self._pending_waits.clear()

        for ws in self._connections:
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()

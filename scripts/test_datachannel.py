"""End-to-end DataChannel test: Nostr signaling + aiortc + ping/pong.

Run two terminals (same machine OK; STUN-less local-only ICE will work):
    Terminal A:  python scripts/test_datachannel.py offerer --room MYROOM
    Terminal B:  python scripts/test_datachannel.py answerer --room MYROOM

Each side opens 'reliable' and 'fast' channels and exchanges 5 ping/pong rounds.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_sync.adapters.logger.stdout_logger import StdoutLogger  # noqa: E402
from blender_sync.adapters.signaling.nostr_provider import NostrSignalingProvider  # noqa: E402
from blender_sync.adapters.transport.aiortc_transport import AiortcTransport  # noqa: E402
from blender_sync.domain.entities import (  # noqa: E402
    ChannelKind,
    IceServer,
    SignalingConfig,
)


async def run_offerer(room: str, relays: tuple[str, ...]) -> None:
    logger = StdoutLogger("dc.offerer")
    transport = AiortcTransport(logger)
    transport.configure((IceServer(url="stun:stun.l.google.com:19302"),))

    received: list[tuple[ChannelKind, bytes]] = []

    def on_recv(kind: ChannelKind, data: bytes) -> None:
        logger.info("RECV [%s] %s", kind.value, data[:80])
        received.append((kind, data))

    transport.on_recv(on_recv)

    offer = await transport.create_offer()
    await transport.gather_complete(8.0)
    full_offer = transport.local_description() or offer

    provider = NostrSignalingProvider(logger, relays)
    await provider.publish_offer(room, full_offer)
    answer = await provider.wait_answer(room, 90.0)
    await transport.accept_answer(answer)
    logger.info("offerer: answer accepted; awaiting datachannel...")

    for _ in range(40):
        await asyncio.sleep(0.25)
        if "reliable" in {c.value for c in transport._channels}:  # type: ignore[attr-defined]
            break

    for i in range(5):
        await transport.send(ChannelKind.RELIABLE, f"reliable-ping-{i}".encode())
        await transport.send(ChannelKind.FAST, f"fast-ping-{i}".encode())
        await asyncio.sleep(0.3)

    await asyncio.sleep(2.0)
    await provider.close()
    await transport.close()
    print(f"OK offerer received {len(received)} messages")


async def run_answerer(room: str, relays: tuple[str, ...]) -> None:
    logger = StdoutLogger("dc.answerer")
    transport = AiortcTransport(logger)
    transport.configure((IceServer(url="stun:stun.l.google.com:19302"),))

    received: list[tuple[ChannelKind, bytes]] = []

    def on_recv(kind: ChannelKind, data: bytes) -> None:
        logger.info("RECV [%s] %s", kind.value, data[:80])
        received.append((kind, data))
        text = data.decode("utf-8", errors="ignore")
        if text.startswith("reliable-ping-"):
            asyncio.create_task(
                transport.send(ChannelKind.RELIABLE, f"pong:{text}".encode())
            )
        elif text.startswith("fast-ping-"):
            asyncio.create_task(
                transport.send(ChannelKind.FAST, f"pong:{text}".encode())
            )

    transport.on_recv(on_recv)

    provider = NostrSignalingProvider(logger, relays)
    offer = await provider.wait_offer(room, 90.0)
    answer = await transport.create_answer(offer)
    await transport.gather_complete(8.0)
    full_answer = transport.local_description() or answer
    await provider.publish_answer(room, full_answer)
    logger.info("answerer: answer published; awaiting messages...")

    await asyncio.sleep(15.0)
    await provider.close()
    await transport.close()
    print(f"OK answerer received {len(received)} messages")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["offerer", "answerer"])
    p.add_argument("--room", required=True)
    p.add_argument(
        "--relays",
        default=",".join(SignalingConfig().nostr_relays),
    )
    args = p.parse_args()

    relays = tuple(r.strip() for r in args.relays.split(",") if r.strip())
    coro = run_offerer(args.room, relays) if args.role == "offerer" \
        else run_answerer(args.room, relays)
    asyncio.run(coro)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

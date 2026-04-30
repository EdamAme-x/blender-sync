"""Standalone integration test for Nostr signaling (no Blender required).

Run two terminals:
    Terminal A:  python scripts/test_signaling.py offerer --room MYROOM
    Terminal B:  python scripts/test_signaling.py answerer --room MYROOM

Both must reach the public Nostr relays. The test exchanges fake SDP strings
and prints success/failure.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_sync.adapters.logger.stdout_logger import StdoutLogger  # noqa: E402
from blender_sync.adapters.signaling.nostr_provider import NostrSignalingProvider  # noqa: E402
from blender_sync.domain.entities import SignalingConfig  # noqa: E402


async def run_offerer(room: str, relays: tuple[str, ...], timeout: float) -> None:
    logger = StdoutLogger("test.offerer")
    provider = NostrSignalingProvider(logger, relays)
    fake_offer = f"v=0\no=- 1 1 IN IP4 0.0.0.0\ns=-\nt=0 0\nROOM={room}\nROLE=offerer\n"
    logger.info("publishing offer to room=%s", room)
    await provider.publish_offer(room, fake_offer)
    logger.info("offer published; waiting for answer (%.1fs)", timeout)
    try:
        answer = await provider.wait_answer(room, timeout)
        logger.info("RECEIVED ANSWER (%d bytes): %s", len(answer), answer.split("\n")[0])
        print("OK offerer received answer")
    finally:
        await provider.close()


async def run_answerer(room: str, relays: tuple[str, ...], timeout: float) -> None:
    logger = StdoutLogger("test.answerer")
    provider = NostrSignalingProvider(logger, relays)
    logger.info("waiting for offer in room=%s", room)
    try:
        offer = await provider.wait_offer(room, timeout)
        logger.info("RECEIVED OFFER (%d bytes): %s", len(offer), offer.split("\n")[0])
        fake_answer = f"v=0\no=- 2 2 IN IP4 0.0.0.0\ns=-\nt=0 0\nROOM={room}\nROLE=answerer\n"
        await provider.publish_answer(room, fake_answer)
        logger.info("answer published")
        print("OK answerer published answer")
    finally:
        await provider.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["offerer", "answerer"])
    p.add_argument("--room", required=True)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument(
        "--relays",
        default=",".join(SignalingConfig().nostr_relays),
    )
    args = p.parse_args()

    relays = tuple(r.strip() for r in args.relays.split(",") if r.strip())
    coro = run_offerer(args.room, relays, args.timeout) if args.role == "offerer" \
        else run_answerer(args.room, relays, args.timeout)
    asyncio.run(coro)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable

from ..domain.ports import IAsyncRunner, ILogger


class AsyncioBackgroundRunner(IAsyncRunner):
    def __init__(self, logger: ILogger) -> None:
        self._logger = logger
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            name="blender-sync-asyncio",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as exc:
                self._logger.warning("asyncio shutdown gather failed: %s", exc)
            loop.close()

    def stop(self) -> None:
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._ready.clear()

    def run_coroutine(self, coro: Awaitable[Any]) -> None:
        if self._loop is None:
            self._logger.warning("async runner not started; coroutine dropped")
            try:
                coro.close()  # type: ignore[union-attr]
            except Exception:
                pass
            return
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]

        def _on_done(fut):
            exc = fut.exception()
            if exc is not None:
                self._logger.error("async task failed: %s", exc)

        future.add_done_callback(_on_done)

    def run_coroutine_blocking(
        self, coro: Awaitable[Any], timeout: float | None = None
    ) -> Any:
        if self._loop is None:
            try:
                coro.close()  # type: ignore[union-attr]
            except Exception:
                pass
            raise RuntimeError("async runner not started")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    def call_soon(self, fn: Callable[..., Any], *args: Any) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(fn, *args)

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

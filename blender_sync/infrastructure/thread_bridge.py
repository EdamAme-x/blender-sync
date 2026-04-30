from __future__ import annotations

import queue
from typing import Generic, TypeVar

T = TypeVar("T")


class ThreadSafeQueue(Generic[T]):
    def __init__(self, maxsize: int = 0) -> None:
        self._q: queue.Queue[T] = queue.Queue(maxsize=maxsize)

    def put(self, item: T) -> None:
        self._q.put_nowait(item)

    def get_nowait(self) -> T | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None

    def drain(self, max_items: int) -> list[T]:
        out: list[T] = []
        for _ in range(max_items):
            item = self.get_nowait()
            if item is None:
                break
            out.append(item)
        return out

    def qsize(self) -> int:
        return self._q.qsize()

    def clear(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

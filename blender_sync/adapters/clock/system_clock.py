from __future__ import annotations

import time

from ...domain.ports import IClock


class SystemClock(IClock):
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

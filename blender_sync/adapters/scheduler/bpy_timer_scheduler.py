from __future__ import annotations

from typing import Callable

from ...domain.ports import IScheduler


class BpyTimerScheduler(IScheduler):
    def __init__(self) -> None:
        self._registered: dict[Callable[[], None], Callable[[], float | None]] = {}

    def schedule(self, callback: Callable[[], None], interval_seconds: float) -> None:
        try:
            import bpy
        except ImportError:
            return

        def wrapper() -> float | None:
            try:
                callback()
            except Exception:
                pass
            return interval_seconds

        self._registered[callback] = wrapper
        bpy.app.timers.register(wrapper, first_interval=interval_seconds, persistent=True)

    def cancel(self, callback: Callable[[], None]) -> None:
        try:
            import bpy
        except ImportError:
            return
        wrapper = self._registered.pop(callback, None)
        if wrapper is None:
            return
        try:
            if bpy.app.timers.is_registered(wrapper):
                bpy.app.timers.unregister(wrapper)
        except Exception:
            pass

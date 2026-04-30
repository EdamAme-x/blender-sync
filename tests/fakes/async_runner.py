import asyncio


class ImmediateAsyncRunner:
    def __init__(self) -> None:
        self.coros = []

    def start(self) -> None: pass
    def stop(self) -> None: pass

    def run_coroutine(self, coro) -> None:
        self.coros.append(coro)
        try:
            asyncio.get_event_loop().run_until_complete(coro)
        except RuntimeError:
            asyncio.new_event_loop().run_until_complete(coro)

    def call_soon(self, fn, *args) -> None:
        fn(*args)

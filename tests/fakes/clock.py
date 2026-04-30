class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self._t = start
        self._mono = 0.0

    def now(self) -> float:
        return self._t

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._t += seconds
        self._mono += seconds

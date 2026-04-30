class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _log(self, level: str, msg: str, *args) -> None:
        try:
            text = msg % args if args else msg
        except Exception:
            text = f"{msg} {args}"
        self.records.append((level, text))

    def debug(self, msg, *args): self._log("DEBUG", msg, *args)
    def info(self, msg, *args): self._log("INFO", msg, *args)
    def warning(self, msg, *args): self._log("WARN", msg, *args)
    def error(self, msg, *args): self._log("ERROR", msg, *args)

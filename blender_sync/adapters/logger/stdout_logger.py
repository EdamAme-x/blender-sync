from __future__ import annotations

import logging
from typing import Any

from ...domain.ports import ILogger


class StdoutLogger(ILogger):
    def __init__(self, name: str = "blender_sync", level: int = logging.INFO) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
            )
            self._logger.addHandler(handler)
        self._logger.setLevel(level)

    def debug(self, msg: str, *args: Any) -> None:
        self._logger.debug(msg, *args)

    def info(self, msg: str, *args: Any) -> None:
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: Any) -> None:
        self._logger.warning(msg, *args)

    def error(self, msg: str, *args: Any) -> None:
        self._logger.error(msg, *args)

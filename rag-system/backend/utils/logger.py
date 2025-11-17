from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from ..config import settings

_LOGGER_CACHE: dict[str, logging.Logger] = {}


def _extra_adapter(logger: logging.Logger) -> logging.LoggerAdapter:
    class SafeAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            extra = kwargs.get("extra", {}) or {}
            safe_extra = {f"extra_{k}": v for k, v in extra.items()}
            kwargs["extra"] = safe_extra
            return msg, kwargs

    return SafeAdapter(logger, {})


def _configure_logger(name: str, log_file: Path, level: int = logging.INFO) -> logging.LoggerAdapter:
    if name in _LOGGER_CACHE:
        return _extra_adapter(_LOGGER_CACHE[name])

    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.propagate = False
    _LOGGER_CACHE[name] = logger
    return _extra_adapter(logger)


def get_logger(name: Optional[str] = None) -> logging.LoggerAdapter:
    key = name or "rag"
    return _configure_logger(key, settings.app_log_file)

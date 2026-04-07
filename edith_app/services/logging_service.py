from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOGGER_CACHE: dict[str, logging.Logger] = {}


def get_logger(name: str, log_path: str) -> logging.Logger:
    cached = _LOGGER_CACHE.get(name)
    if cached is not None:
        return cached

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _LOGGER_CACHE[name] = logger
    return logger

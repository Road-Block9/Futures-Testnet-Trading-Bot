"""Safe file logging configuration for the trading bot."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


LOGGER_NAME = "trading_bot"
LOG_DIRECTORY = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIRECTORY / "trading_bot.log"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging() -> logging.Logger:
    """Configure append-only logging, falling back safely on read-only hosts."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    try:
        LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        expected_path = LOG_FILE.resolve()
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                if Path(handler.baseFilename).resolve() == expected_path:
                    return logger

        handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
    except OSError:
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
    return logger


def safe_log_value(value: Any, *, maximum_length: int = 200) -> str:
    """Flatten control characters and bound a non-sensitive value for logging."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) > maximum_length:
        return text[:maximum_length] + "…"
    return text

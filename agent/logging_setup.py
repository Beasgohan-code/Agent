"""Agent — logging configuration.

Logs go to stdout unbuffered so Render captures them in real time.
"""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Chatty third-party loggers; the bot's own logs stay informative.
NOISY_LOGGERS = ("pyrogram", "wzgram", "richgram", "asyncio")
VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def configure_logging(level: str = "INFO") -> None:
    """Install the Agent log handler (idempotent)."""
    resolved = (level or "INFO").strip().upper()
    if resolved not in VALID_LEVELS:
        resolved = "INFO"

    root = logging.getLogger()
    root.setLevel(resolved)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(handler)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, getattr(logging, resolved)))

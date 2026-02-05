#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Helpers for working with httpx."""

from contextlib import contextmanager
import logging
from typing import Iterator


@contextmanager
def silence_httpx() -> Iterator[None]:
    """Temporarily suppress httpx/httpcore logging."""
    logger_names = ("httpx", "httpcore")
    previous_levels: dict[str, int] = {}

    for name in logger_names:
        logger = logging.getLogger(name)
        previous_levels[name] = logger.level
        logger.setLevel(logging.CRITICAL)

    try:
        yield
    finally:
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)

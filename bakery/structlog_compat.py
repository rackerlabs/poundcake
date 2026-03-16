"""Minimal structlog compatibility shim for environments without structlog."""

from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from typing import Any


class _BoundLogger:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("bakery")

    def info(self, event: str, **kwargs: Any) -> None:
        self._logger.info("%s %s", event, kwargs if kwargs else "")

    def error(self, event: str, **kwargs: Any) -> None:
        self._logger.error("%s %s", event, kwargs if kwargs else "")

    def warning(self, event: str, **kwargs: Any) -> None:
        self._logger.warning("%s %s", event, kwargs if kwargs else "")


def _processor(*_args: Any, **_kwargs: Any):
    return lambda _logger, _method_name, event_dict: event_dict


class _LoggerFactory:
    def __call__(self, *args: Any, **kwargs: Any) -> logging.Logger:
        return logging.getLogger(kwargs.get("name", "bakery"))


def configure(**_kwargs: Any) -> None:
    return None


def get_logger(*_args: Any, **_kwargs: Any) -> _BoundLogger:
    return _BoundLogger()


_fallback_structlog = SimpleNamespace(
    configure=configure,
    get_logger=get_logger,
    stdlib=SimpleNamespace(
        filter_by_level=_processor(),
        add_logger_name=_processor(),
        add_log_level=_processor(),
        PositionalArgumentsFormatter=lambda: _processor(),
        BoundLogger=_BoundLogger,
        LoggerFactory=_LoggerFactory,
    ),
    processors=SimpleNamespace(
        TimeStamper=lambda fmt="iso": _processor(),
        StackInfoRenderer=lambda: _processor(),
        format_exc_info=_processor(),
        UnicodeDecoder=lambda: _processor(),
        JSONRenderer=lambda: _processor(),
    ),
)

try:
    structlog = importlib.import_module("structlog")
except ImportError:  # pragma: no cover - exercised in lightweight local envs
    structlog = _fallback_structlog

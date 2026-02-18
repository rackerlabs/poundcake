#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Logging configuration."""

import logging
import sys
import os
from pythonjsonlogger.json import JsonFormatter
from api.core.config import settings

INSTANCE_ID = os.getenv("POD_NAME") or os.getenv("HOSTNAME") or "local"
SERVICE_NAME = os.getenv("SERVICE_NAME") or os.getenv("SERVICE") or "unknown"


class InstanceIdFilter(logging.Filter):
    """Inject instance_id into all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "instance_id"):
            record.instance_id = INSTANCE_ID
        if not hasattr(record, "service"):
            record.service = SERVICE_NAME
        return True


class KeyValueConsoleFormatter(logging.Formatter):
    """Console formatter that appends extra fields as key=value pairs."""

    _reserved = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "instance_id",
        "service",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Ensure req_id always exists for format string
        req_id = getattr(record, "req_id", "SYSTEM")
        instance_id = getattr(record, "instance_id", INSTANCE_ID)
        service = getattr(record, "service", SERVICE_NAME)
        method = getattr(record, "method", None) or getattr(record, "http_method", None) or "NA"
        status_code = (
            getattr(record, "status_code", None) or getattr(record, "http_status", None) or "NA"
        )
        latency_ms = (
            getattr(record, "latency_ms", None)
            or getattr(record, "processing_time_ms", None)
            or "NA"
        )

        # Strip redundant "funcName:" prefix if present
        message = record.getMessage()
        func_prefix = f"{record.funcName}:"
        if message.startswith(func_prefix):
            message = message[len(func_prefix) :].lstrip()

        timestamp = self.formatTime(record, self.datefmt)
        base = (
            f"{timestamp} [{req_id}] [{instance_id}] [{service}] [{record.levelname}] [{method}] "
            f"status={status_code} latency_ms={latency_ms} {record.funcName} - {message}"
        )
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._reserved
            and key
            not in {
                "req_id",
                "method",
                "http_method",
                "status_code",
                "http_status",
                "latency_ms",
                "processing_time_ms",
                "instance_id",
                "service",
            }
        }
        if not extras:
            return base

        extra_parts = " ".join(f"{key}={value}" for key, value in sorted(extras.items()))
        return f"{base} {extra_parts}"


def setup_logging() -> None:
    """Configure application logging."""

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(InstanceIdFilter())

    # Configure formatter based on settings
    if settings.log_format == "json":
        formatter = JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
        )
    else:
        # Standard format: [datetime] [req_id] LEVEL - function_name: message
        formatter = KeyValueConsoleFormatter(
            "%(asctime)s [%(req_id)s] %(levelname)s %(funcName)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Set third-party loggers to WARNING (suppresses INFO and DEBUG)
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Set httpx/httpcore to ERROR (suppress WARNING/INFO/DEBUG by default)
    for logger_name in ["httpx", "httpcore"]:
        logging.getLogger(logger_name).setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)

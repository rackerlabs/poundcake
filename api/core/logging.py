#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Logging configuration."""

import logging
import sys
from pythonjsonlogger.json import JsonFormatter
from api.core.config import settings


def setup_logging() -> None:
    """Configure application logging."""

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)

    # Configure formatter based on settings
    if settings.log_format == "json":
        formatter = JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d %(req_id)s",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
        )
    else:
        # Standard format: [datetime] [req_id] LEVEL - function_name: message
        formatter = logging.Formatter(
            "%(asctime)s [%(req_id)s] %(levelname)s - %(message)s", 
            datefmt="%Y-%m-%d %H:%M:%S",
            defaults={"req_id": "NONE"}  # Default value if req_id not provided
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Set third-party loggers to WARNING
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "celery", "sqlalchemy"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)

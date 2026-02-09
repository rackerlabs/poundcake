#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Startup checks for external dependencies."""

from __future__ import annotations

import asyncio
from pathlib import Path

from api.core.logging import get_logger
from api.services.stackstorm_service import get_stackstorm_client
from api.core.config import get_settings

logger = get_logger(__name__)

ST2_KEY_FILE = Path("/app/config/st2_api_key")


async def wait_for_stackstorm_ready(max_attempts: int = 60, delay_sec: float = 2.0) -> bool:
    """Wait for StackStorm API key and API health before declaring ready."""
    settings = get_settings()
    client = get_stackstorm_client()

    for attempt in range(1, max_attempts + 1):
        api_key = settings.get_stackstorm_api_key()
        if not api_key:
            logger.info(
                "Waiting for StackStorm API key",
                extra={"attempt": attempt, "max_attempts": max_attempts},
            )
            await asyncio.sleep(delay_sec)
            continue

        is_healthy = await client.health_check(req_id="SYSTEM-STARTUP")
        if is_healthy:
            logger.info("StackStorm API is ready", extra={"attempt": attempt})
            return True

        logger.info(
            "Waiting for StackStorm API health",
            extra={"attempt": attempt, "max_attempts": max_attempts},
        )
        await asyncio.sleep(delay_sec)

    logger.warning(
        "StackStorm API did not become ready before startup timeout",
        extra={"max_attempts": max_attempts},
    )
    return False

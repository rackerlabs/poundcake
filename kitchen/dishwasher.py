#!/usr/bin/env python3
#  ____                        _  ____      _
# |  _ \\ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \\| | | | '_ \\ / _` | |   / _` | |/ / _ \\
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \\___/ \\__,_|_| |_|\\__,_|\\____\\__,_|_|\\_\\___|
#
"""Dishwasher: trigger StackStorm sync via PoundCake API."""

import os
import time
from api.core.http_client import request_with_retry_sync

from api.core.logging import setup_logging, get_logger
from api.core.config import get_settings
from kitchen.service_helpers import wait_for_api

setup_logging()
logger = get_logger("dishwasher")

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
DISHWASHER_INTERVAL = int(os.getenv("DISHWASHER_INTERVAL", "0"))
MARK_BOOTSTRAP = os.getenv("POUNDCAKE_BOOTSTRAP_MARK", "false").lower() == "true"

SYSTEM_REQ_ID = "SYSTEM-DISHWASHER"
POLLER_RETRIES = get_settings().poller_http_retries


def run_sync() -> bool:
    params = {"mark_bootstrap": "true"} if MARK_BOOTSTRAP else {}
    try:
        start_time = time.time()
        resp = request_with_retry_sync(
            "POST",
            f"{API_BASE_URL}/cook/sync",
            params=params,
            headers={"X-Request-ID": SYSTEM_REQ_ID},
            timeout=60,
            retries=POLLER_RETRIES,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        if resp.status_code not in (200, 201):
            logger.error(
                "Dishwasher sync failed",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "response": resp.text,
                },
            )
            return False
        logger.info(
            "Dishwasher sync complete",
            extra={
                "req_id": SYSTEM_REQ_ID,
                "latency_ms": latency_ms,
                "stats": resp.json(),
            },
        )
        return True
    except Exception as e:
        logger.error(
            "Dishwasher sync error",
            extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
        )
        return False


def main() -> None:
    wait_for_api(
        API_BASE_URL, SYSTEM_REQ_ID, logger, require_healthy=False, max_attempts=120, delay_sec=2.0
    )

    if DISHWASHER_INTERVAL <= 0:
        attempts = int(os.getenv("DISHWASHER_BOOTSTRAP_ATTEMPTS", "10"))
        retry_delay = float(os.getenv("DISHWASHER_BOOTSTRAP_RETRY_DELAY", "5"))
        for attempt in range(1, attempts + 1):
            if run_sync():
                return
            if attempt < attempts:
                logger.warning(
                    "Dishwasher bootstrap sync failed; retrying",
                    extra={"req_id": SYSTEM_REQ_ID, "attempt": attempt, "max_attempts": attempts},
                )
                time.sleep(retry_delay)
        logger.error(
            "Dishwasher bootstrap sync failed after max attempts",
            extra={"req_id": SYSTEM_REQ_ID, "max_attempts": attempts},
        )
        return

    logger.info(
        "Dishwasher starting in periodic mode",
        extra={"req_id": SYSTEM_REQ_ID, "interval_sec": DISHWASHER_INTERVAL},
    )
    while True:
        run_sync()
        time.sleep(DISHWASHER_INTERVAL)


if __name__ == "__main__":
    main()

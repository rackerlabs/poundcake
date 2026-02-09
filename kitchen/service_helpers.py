#!/usr/bin/env python3
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Shared helpers for kitchen services."""

import time
from api.core.http_client import request_with_retry_sync
from api.core.config import get_settings


def wait_for_api(
    api_base_url: str,
    system_req_id: str,
    logger,
    max_attempts: int = 60,
    delay_sec: float = 2.0,
    require_healthy: bool = True,
    retries: int | None = None,
) -> bool:
    """Wait for PoundCake API health before starting service loops."""
    logger.info(
        "Waiting for API to be ready",
        extra={"req_id": system_req_id, "api_url": api_base_url},
    )

    for attempt in range(1, max_attempts + 1):
        try:
            start_time = time.time()
            if retries is None:
                retries = get_settings().poller_http_retries
            resp = request_with_retry_sync(
                "GET",
                f"{api_base_url}/health",
                timeout=5,
                retries=retries,
            )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code == 200 or (not require_healthy and resp.status_code == 503):
                logger.info(
                    "API is ready",
                    extra={
                        "req_id": system_req_id,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return True
        except Exception:
            pass

        if attempt < max_attempts:
            time.sleep(delay_sec)

    logger.warning(
        "API did not become ready. Starting anyway...",
        extra={"req_id": system_req_id, "max_attempts": max_attempts},
    )
    return False

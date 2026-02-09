#!/usr/bin/env python3
"""Shared helpers for kitchen services."""

import time
from typing import Any
import httpx


def wait_for_api(
    api_base_url: str,
    system_req_id: str,
    logger: Any,
    max_attempts: int = 60,
    delay_sec: float = 2.0,
    require_healthy: bool = True,
) -> bool:
    """Wait for PoundCake API health before starting service loops."""
    logger.info(
        "Waiting for API to be ready",
        extra={"req_id": system_req_id, "api_url": api_base_url},
    )

    for attempt in range(1, max_attempts + 1):
        try:
            start_time = time.time()
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{api_base_url}/health")
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

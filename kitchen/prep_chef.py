#!/usr/bin/env python3
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prep Chef: Polls for new alerts and triggers the /bake API"""

import os
import time
import httpx

from api.core.logging import setup_logging, get_logger

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_URL = f"{POUNDCAKE_API_URL}/api/v1"
OVEN_INTERVAL = int(os.getenv("OVEN_INTERVAL", "5"))

# System request ID for prep chef operations
SYSTEM_REQ_ID = "SYSTEM-PREP-CHEF"


def wait_for_api():
    """Wait for API to be ready before starting main loop."""
    logger.info(
        "Waiting for API to be ready",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL},
    )
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            start_time = time.time()
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{API_URL}/health")
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                logger.info(
                    "API is ready! Starting prep chef...",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return True
        except Exception:
            pass

        attempt += 1
        if attempt < max_attempts:
            time.sleep(2)  # Check every 2 seconds

    logger.warning(
        "API did not become ready. Starting anyway...",
        extra={"req_id": SYSTEM_REQ_ID, "max_attempts": max_attempts},
    )
    return False


def prep_loop():
    """Main prep chef loop - polls for new alerts and triggers baking."""
    wait_for_api()
    logger.info(
        "Starting prep chef",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL, "poll_interval": OVEN_INTERVAL},
    )

    while True:
        try:
            # Fetch alerts.process_status of 'new' (crawler)
            start_time = time.time()
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{API_URL}/alerts", params={"processing_status": "new"}
                )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch new alerts",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                time.sleep(OVEN_INTERVAL)
                continue
            alerts = resp.json()

            for alert in alerts:
                req_id = alert.get("req_id", "UNKNOWN")
                alert_id = alert.get("id")

                # Pass the original Request ID to the next hop
                headers = {"X-Request-ID": req_id}

                logger.info(
                    f"Preparing alert with id {alert_id} for baking",
                    extra={"req_id": req_id, "alert_id": alert_id},
                )

                start_time = time.time()
                with httpx.Client(timeout=15) as client:
                    bake_resp = client.post(
                        f"{API_URL}/ovens/bake/{alert_id}", headers=headers
                    )
                latency_ms = int((time.time() - start_time) * 1000)

                if bake_resp.status_code in [200, 201]:
                    logger.info(
                        f"Successfully prepared alert with id {alert_id} for oven",
                        extra={
                            "req_id": req_id,
                            "alert_id": alert_id,
                            "method": "POST",
                            "status_code": bake_resp.status_code,
                            "latency_ms": latency_ms,
                        },
                    )
                else:
                    logger.error(
                        "Bake preparation failed",
                        extra={
                            "req_id": req_id,
                            "alert_id": alert_id,
                            "method": "POST",
                            "status_code": bake_resp.status_code,
                            "latency_ms": latency_ms,
                            "response": bake_resp.text,
                        },
                    )

        except Exception as e:
            logger.error(
                "Prep chef loop error", extra={"req_id": SYSTEM_REQ_ID, "error": str(e)}
            )

        time.sleep(OVEN_INTERVAL)


if __name__ == "__main__":
    prep_loop()

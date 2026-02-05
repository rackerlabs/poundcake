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
import requests

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
        "wait_for_api: Waiting for API to be ready",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL},
    )
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            resp = requests.get(f"{API_URL}/health", timeout=5)
            if resp.status_code == 200:
                logger.info(
                    "wait_for_api: API is ready! Starting prep chef...",
                    extra={"req_id": SYSTEM_REQ_ID},
                )
                return True
        except Exception:
            pass

        attempt += 1
        if attempt < max_attempts:
            time.sleep(2)  # Check every 2 seconds

    logger.warning(
        "wait_for_api: API did not become ready. Starting anyway...",
        extra={"req_id": SYSTEM_REQ_ID, "max_attempts": max_attempts},
    )
    return False


def prep_loop():
    """Main prep chef loop - polls for new alerts and triggers baking."""
    wait_for_api()
    logger.info(
        "prep_loop: Starting prep chef",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL, "poll_interval": OVEN_INTERVAL},
    )

    while True:
        try:
            # Fetch alerts.process_status of 'new' (crawler)
            resp = requests.get(
                f"{API_URL}/alerts", params={"processing_status": "new"}, timeout=10
            )
            resp.raise_for_status()
            alerts = resp.json()

            for alert in alerts:
                req_id = alert.get("req_id", "UNKNOWN")
                alert_id = alert.get("id")

                # Pass the original Request ID to the next hop
                headers = {"X-Request-ID": req_id}

                logger.info(
                    f"prep_loop: Preparing alert with id {alert_id} for baking",
                    extra={"req_id": req_id, "alert_id": alert_id},
                )

                bake_resp = requests.post(
                    f"{API_URL}/ovens/bake/{alert_id}", headers=headers, timeout=15
                )

                if bake_resp.status_code in [200, 201]:
                    logger.info(
                        f"prep_loop: Successfully prepared alert with id {alert_id} for oven",
                        extra={"req_id": req_id, "alert_id": alert_id},
                    )
                else:
                    logger.error(
                        "prep_loop: Bake preparation failed",
                        extra={
                            "req_id": req_id,
                            "alert_id": alert_id,
                            "status_code": bake_resp.status_code,
                            "response": bake_resp.text,
                        },
                    )

        except Exception as e:
            logger.error(
                "prep_loop: Prep chef loop error", extra={"req_id": SYSTEM_REQ_ID, "error": str(e)}
            )

        time.sleep(OVEN_INTERVAL)


if __name__ == "__main__":
    prep_loop()

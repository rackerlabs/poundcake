#!/usr/bin/env python3
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prep Chef: Polls for new orders and triggers the /dishes/cook API"""

import os
import time
import httpx

from api.core.logging import setup_logging, get_logger
from kitchen.service_helpers import wait_for_api

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_URL = f"{POUNDCAKE_API_URL}/api/v1"
OVEN_INTERVAL = int(os.getenv("OVEN_INTERVAL", "5"))

# System request ID for prep chef operations
SYSTEM_REQ_ID = "SYSTEM-PREP-CHEF"


def prep_loop() -> None:
    """Main prep chef loop - polls for new orders and triggers cooking."""
    wait_for_api(API_URL, SYSTEM_REQ_ID, logger)
    logger.info(
        "Starting prep chef",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL, "poll_interval": OVEN_INTERVAL},
    )

    while True:
        try:
            # Fetch orders with processing_status = 'new'
            start_time = time.time()
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{API_URL}/orders", params={"processing_status": "new"})
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch new orders",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                time.sleep(OVEN_INTERVAL)
                continue
            orders = resp.json()

            for order in orders:
                req_id = order.get("req_id", "UNKNOWN")
                order_id = order.get("id")

                # Pass the original Request ID to the next hop
                headers = {"X-Request-ID": req_id}

                logger.info(
                    "Preparing order for cooking",
                    extra={"req_id": req_id, "order_id": order_id},
                )

                start_time = time.time()
                with httpx.Client(timeout=15) as client:
                    cook_resp = client.post(f"{API_URL}/dishes/cook/{order_id}", headers=headers)
                latency_ms = int((time.time() - start_time) * 1000)

                if cook_resp.status_code in [200, 201]:
                    logger.info(
                        "Successfully prepared order for dish",
                        extra={
                            "req_id": req_id,
                            "order_id": order_id,
                            "method": "POST",
                            "status_code": cook_resp.status_code,
                            "latency_ms": latency_ms,
                        },
                    )
                else:
                    logger.error(
                        "Cook preparation failed",
                        extra={
                            "req_id": req_id,
                            "order_id": order_id,
                            "method": "POST",
                            "status_code": cook_resp.status_code,
                            "latency_ms": latency_ms,
                            "response": cook_resp.text,
                        },
                    )

        except Exception as e:
            logger.error("Prep chef loop error", extra={"req_id": SYSTEM_REQ_ID, "error": str(e)})

        time.sleep(OVEN_INTERVAL)


if __name__ == "__main__":
    prep_loop()

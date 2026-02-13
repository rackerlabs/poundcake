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
from api.core.http_client import request_with_retry_sync

from api.core.logging import setup_logging, get_logger
from api.core.config import get_settings
from kitchen.service_helpers import wait_for_api

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_URL = f"{POUNDCAKE_API_URL}/api/v1"
PREP_INTERVAL = int(os.getenv("PREP_INTERVAL", "5"))

# System request ID for prep chef operations
SYSTEM_REQ_ID = "SYSTEM-PREP-CHEF"
POLLER_RETRIES = get_settings().poller_http_retries
POLL_LIMIT = int(os.getenv("PREP_CHEF_LIMIT", "1"))


def prep_loop() -> None:
    """Main prep chef loop - polls for new orders and triggers cooking."""
    wait_for_api(API_URL, SYSTEM_REQ_ID, logger)
    logger.info(
        "Starting prep chef",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL, "poll_interval": PREP_INTERVAL},
    )
    api_unavailable_since: float | None = None

    while True:
        try:
            # Fetch orders with processing_status = 'new'
            start_time = time.time()
            resp = request_with_retry_sync(
                "GET",
                f"{API_URL}/orders",
                params={"processing_status": "new", "limit": POLL_LIMIT},
                timeout=10,
                retries=POLLER_RETRIES,
            )
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
                time.sleep(PREP_INTERVAL)
                continue

            if api_unavailable_since is not None:
                downtime_sec = int(time.time() - api_unavailable_since)
                logger.info(
                    "Prep chef API connectivity restored",
                    extra={"req_id": SYSTEM_REQ_ID, "downtime_sec": downtime_sec},
                )
                api_unavailable_since = None

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
                cook_resp = request_with_retry_sync(
                    "POST",
                    f"{API_URL}/dishes/cook/{order_id}",
                    headers=headers,
                    timeout=15,
                    retries=POLLER_RETRIES,
                )
                latency_ms = int((time.time() - start_time) * 1000)

                if cook_resp.status_code in [200, 201]:
                    cook_status = "unknown"
                    try:
                        cook_status = cook_resp.json().get("status", "unknown")
                    except Exception:
                        cook_status = "unknown"
                    logger.info(
                        "Order prepared",
                        extra={
                            "req_id": req_id,
                            "order_id": order_id,
                            "cook_status": cook_status,
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
            if api_unavailable_since is None:
                api_unavailable_since = time.time()
                logger.error(
                    "Prep chef lost API connectivity",
                    extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
                )
            else:
                logger.debug(
                    "Prep chef waiting for API recovery",
                    extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
                )

        time.sleep(PREP_INTERVAL)


if __name__ == "__main__":
    prep_loop()

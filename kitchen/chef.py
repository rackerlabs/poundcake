#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Chef: Polls for pending Dish tasks and executes workflows via StackStorm"""

import os
import time
from api.core.http_client import request_with_retry_sync

from api.core.logging import setup_logging, get_logger
from api.core.config import get_settings
from kitchen.service_helpers import wait_for_api

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

# Config
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
POLL_INTERVAL = int(os.getenv("OVEN_POLL_INTERVAL", "5"))

# System request ID for polling operations
SYSTEM_REQ_ID = "SYSTEM-CHEF"
POLLER_RETRIES = get_settings().poller_http_retries
CHEF_PATCH_RETRIES = get_settings().chef_patch_retries
CHEF_PATCH_RETRY_BACKOFF_SECONDS = get_settings().chef_patch_retry_backoff_seconds


def run_chef() -> None:
    """Main chef loop - polls for dishes and executes workflows."""
    wait_for_api(API_BASE_URL, SYSTEM_REQ_ID, logger)

    logger.info(
        "Chef started",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL, "poll_interval": POLL_INTERVAL},
    )

    while True:
        try:
            # Fetch next 'new' dish
            start_time = time.time()
            resp = request_with_retry_sync(
                "GET",
                f"{API_BASE_URL}/dishes",
                params={"processing_status": "new", "limit": 1},
                headers={"X-Request-ID": SYSTEM_REQ_ID},
                timeout=10,
                retries=POLLER_RETRIES,
            )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch dishes",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                time.sleep(POLL_INTERVAL)
                continue

            dishes = resp.json()
            if not dishes:
                time.sleep(POLL_INTERVAL)
                continue

            dish = dishes[0]
            dish_id = dish.get("id")
            req_id = dish.get("req_id") or "UNKNOWN"

            # Step 1: claim dish atomically
            claim_resp = request_with_retry_sync(
                "POST",
                f"{API_BASE_URL}/dishes/{dish_id}/claim",
                headers={"X-Request-ID": req_id},
                timeout=10,
                retries=POLLER_RETRIES,
            )
            if claim_resp.status_code == 409:
                time.sleep(POLL_INTERVAL)
                continue
            if claim_resp.status_code != 200:
                logger.error(
                    "Failed to claim dish",
                    extra={
                        "req_id": req_id,
                        "dish_id": dish_id,
                        "status_code": claim_resp.status_code,
                    },
                )
                time.sleep(POLL_INTERVAL)
                continue

            dish = claim_resp.json()
            recipe = dish.get("recipe") or {}

            workflow_id = recipe.get("workflow_id")
            workflow_parameters = recipe.get("workflow_parameters") or {}

            # Step 2: if workflow_id exists, confirm in ST2
            if workflow_id:
                resp = request_with_retry_sync(
                    "GET",
                    f"{API_BASE_URL}/cook/actions/{workflow_id}",
                    headers={"X-Request-ID": req_id},
                    timeout=10,
                    retries=POLLER_RETRIES,
                )
                if resp.status_code != 200:
                    workflow_id = None

            # Step 3/4: register workflow if missing
            if not workflow_id:
                try:
                    reg_resp = request_with_retry_sync(
                        "POST",
                        f"{API_BASE_URL}/cook/workflows/register",
                        json=recipe,
                        headers={"X-Request-ID": req_id},
                        timeout=30,
                        retries=POLLER_RETRIES,
                    )
                    if reg_resp.status_code not in (200, 201):
                        raise Exception(reg_resp.text)
                    workflow_id = reg_resp.json().get("workflow_id")

                    # Store workflow_id (and generated payload if needed)
                    request_with_retry_sync(
                        "PATCH",
                        f"{API_BASE_URL}/recipes/{recipe.get('id')}",
                        json={
                            "workflow_id": workflow_id,
                        },
                        headers={"X-Request-ID": req_id},
                        timeout=10,
                        retries=POLLER_RETRIES,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to register workflow",
                        extra={"req_id": req_id, "dish_id": dish_id, "error": str(e)},
                    )
                    request_with_retry_sync(
                        "PATCH",
                        f"{API_BASE_URL}/dishes/{dish_id}",
                        json={"processing_status": "failed", "error_message": str(e)},
                        headers={"X-Request-ID": req_id},
                        timeout=10,
                        retries=POLLER_RETRIES,
                    )
                    time.sleep(POLL_INTERVAL)
                    continue

            # Execute workflow
            try:
                exec_resp = request_with_retry_sync(
                    "POST",
                    f"{API_BASE_URL}/cook/execute",
                    json={"action": workflow_id, "parameters": workflow_parameters},
                    headers={"X-Request-ID": req_id},
                    timeout=30,
                    retries=POLLER_RETRIES,
                )
                if exec_resp.status_code not in (200, 201):
                    raise Exception(exec_resp.text)
                st2_exec_id = exec_resp.json().get("id")

                patch_resp = request_with_retry_sync(
                    "PATCH",
                    f"{API_BASE_URL}/dishes/{dish_id}",
                    json={"workflow_execution_id": st2_exec_id},
                    headers={"X-Request-ID": req_id},
                    timeout=10,
                    retries=CHEF_PATCH_RETRIES,
                    retry_backoff_seconds=CHEF_PATCH_RETRY_BACKOFF_SECONDS,
                )
                if patch_resp.status_code not in (200, 201):
                    logger.error(
                        "Failed to persist workflow execution id",
                        extra={
                            "req_id": req_id,
                            "dish_id": dish_id,
                            "status_code": patch_resp.status_code,
                            "response": patch_resp.text,
                        },
                    )

                logger.info(
                    "Workflow execution started",
                    extra={
                        "req_id": req_id,
                        "dish_id": dish_id,
                        "workflow_id": workflow_id,
                        "execution_id": st2_exec_id,
                    },
                )

            except Exception as e:
                logger.error(
                    "Workflow execution failed",
                    extra={"req_id": req_id, "dish_id": dish_id, "error": str(e)},
                )
                request_with_retry_sync(
                    "PATCH",
                    f"{API_BASE_URL}/dishes/{dish_id}",
                    json={"processing_status": "failed", "error_message": str(e)},
                    headers={"X-Request-ID": req_id},
                    timeout=10,
                    retries=POLLER_RETRIES,
                )

        except Exception as e:
            logger.error(
                "Chef loop encountered an error",
                extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
            )
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_chef()

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
from kitchen.service_helpers import wait_for_api, get_service_headers

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

# Config
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://poundcake:8080").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
POLL_INTERVAL = int(os.getenv("CHEF_POLL_INTERVAL", "5"))

# System request ID for polling operations
SYSTEM_REQ_ID = "SYSTEM-CHEF"
POLLER_RETRIES = get_settings().poller_http_retries
CHEF_PATCH_RETRIES = get_settings().chef_patch_retries
CHEF_PATCH_RETRY_BACKOFF_SECONDS = get_settings().chef_patch_retry_backoff_seconds
CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES = max(
    0, get_settings().chef_execute_missing_workflow_retries
)
CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS = max(
    0.1, get_settings().chef_execute_missing_workflow_retry_backoff_seconds
)
MISSING_WORKFLOW_PATH_FRAGMENT = "/opt/stackstorm/packs/poundcake/actions/workflows/"


def _is_missing_workflow_file_response(response_text: str | None) -> bool:
    if not isinstance(response_text, str):
        return False
    return (
        "No such file or directory" in response_text
        and MISSING_WORKFLOW_PATH_FRAGMENT in response_text
    )


def run_chef() -> None:
    """Main chef loop - polls for dishes and executes workflows."""
    wait_for_api(API_BASE_URL, SYSTEM_REQ_ID, logger)

    logger.info(
        "Chef started",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL, "poll_interval": POLL_INTERVAL},
    )
    api_unavailable_since: float | None = None

    while True:
        try:
            # Fetch next 'new' dish
            start_time = time.time()
            resp = request_with_retry_sync(
                "GET",
                f"{API_BASE_URL}/dishes",
                params={"processing_status": "new", "limit": 1},
                headers=get_service_headers(SYSTEM_REQ_ID),
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

            if api_unavailable_since is not None:
                downtime_sec = int(time.time() - api_unavailable_since)
                logger.info(
                    "Chef API connectivity restored",
                    extra={"req_id": SYSTEM_REQ_ID, "downtime_sec": downtime_sec},
                )
                api_unavailable_since = None

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
                headers=get_service_headers(req_id),
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
            try:
                reg_resp = request_with_retry_sync(
                    "POST",
                    f"{API_BASE_URL}/cook/workflows/register",
                    json=recipe,
                    headers=get_service_headers(req_id),
                    timeout=30,
                    retries=POLLER_RETRIES,
                )
                if reg_resp.status_code not in (200, 201):
                    raise Exception(reg_resp.text)
                workflow_id = reg_resp.json().get("workflow_id")
            except Exception as e:
                logger.error(
                    "Failed to register workflow",
                    extra={"req_id": req_id, "dish_id": dish_id, "error": str(e)},
                )
                request_with_retry_sync(
                    "PATCH",
                    f"{API_BASE_URL}/dishes/{dish_id}",
                    json={"processing_status": "failed", "error_message": str(e)},
                    headers=get_service_headers(req_id),
                    timeout=10,
                    retries=POLLER_RETRIES,
                )
                time.sleep(POLL_INTERVAL)
                continue

            # Execute workflow
            try:
                st2_exec_id = None
                max_attempts = 1 + CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES
                for attempt in range(1, max_attempts + 1):
                    exec_resp = request_with_retry_sync(
                        "POST",
                        f"{API_BASE_URL}/cook/execute",
                        json={"action": workflow_id, "parameters": {}},
                        headers=get_service_headers(req_id),
                        timeout=30,
                        retries=POLLER_RETRIES,
                    )
                    if exec_resp.status_code in (200, 201):
                        st2_exec_id = exec_resp.json().get("id")
                        break

                    if (
                        attempt < max_attempts
                        and _is_missing_workflow_file_response(exec_resp.text)
                    ):
                        logger.warning(
                            "Workflow file not yet available on StackStorm runner; retrying execution",
                            extra={
                                "req_id": req_id,
                                "dish_id": dish_id,
                                "workflow_id": workflow_id,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                            },
                        )
                        time.sleep(CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS)
                        continue

                    raise Exception(exec_resp.text)

                if not st2_exec_id:
                    raise Exception(
                        "StackStorm execution did not return an execution id after retries"
                    )

                patch_resp = request_with_retry_sync(
                    "PATCH",
                    f"{API_BASE_URL}/dishes/{dish_id}",
                    json={"execution_ref": st2_exec_id},
                    headers=get_service_headers(req_id),
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
                    headers=get_service_headers(req_id),
                    timeout=10,
                    retries=POLLER_RETRIES,
                )

        except Exception as e:
            if api_unavailable_since is None:
                api_unavailable_since = time.time()
                logger.error(
                    "Chef lost API connectivity",
                    extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
                )
            else:
                logger.debug(
                    "Chef waiting for API recovery",
                    extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
                )
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_chef()

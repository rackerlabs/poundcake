#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Chef: Polls for pending Oven tasks and executes them via StackStorm"""

import os
import time
import requests
from datetime import datetime, timezone

from api.core.logging import setup_logging, get_logger

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

# Config: No ST2 keys required here!
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
POLL_INTERVAL = int(os.getenv("OVEN_POLL_INTERVAL", "5"))

# System request ID for polling operations (distinguishes system calls from alert processing)
SYSTEM_REQ_ID = "SYSTEM-CHEF"


def wait_for_api():
    """Wait for API to be ready before starting main loop."""
    logger.info(
        "wait_for_api: Waiting for API to be ready",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL},
    )
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            resp = requests.get(f"{API_BASE_URL.rsplit('/api/v1', 1)[0]}/api/v1/health", timeout=5)
            if resp.status_code == 200:
                logger.info(
                    "wait_for_api: API is ready! Starting chef...", extra={"req_id": SYSTEM_REQ_ID}
                )
                return True
        except Exception:
            pass

        attempt += 1
        if attempt < max_attempts:
            time.sleep(2)

    logger.error(
        "wait_for_api: API did not become ready. Starting anyway...",
        extra={"req_id": SYSTEM_REQ_ID, "max_attempts": max_attempts},
    )
    return False


def run_chef():
    """Main chef loop - polls for oven tasks and executes them."""
    # Wait for API to be ready
    wait_for_api()

    logger.info(
        "run_chef: Chef started",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL, "poll_interval": POLL_INTERVAL},
    )

    while True:
        try:
            # Fetch next 'new' oven task
            resp = requests.get(
                f"{API_BASE_URL}/ovens",
                params={"processing_status": "new", "limit": 1},
                headers={"X-Request-ID": SYSTEM_REQ_ID},
            )
            resp.raise_for_status()
            tasks = resp.json()

            if not tasks:
                time.sleep(POLL_INTERVAL)
                continue

            task = tasks[0]
            oven_id = task["id"]

            # Switch from system polling req_id to alert's req_id for all subsequent operations
            req_id = task["req_id"]

            # Get ingredient details (includes st2_action and parameters)
            ingredient = task.get("ingredient", {})
            action_ref = ingredient.get("st2_action")
            parameters = ingredient.get("parameters", {})

            if not action_ref:
                logger.error(
                    "run_chef: No action_ref found for Oven",
                    extra={"req_id": req_id, "oven_id": oven_id},
                )
                time.sleep(POLL_INTERVAL)
                continue

            # Proxy the request through the API Bridge
            logger.info(
                "run_chef: Cooking action with ref {action_ref} via API bridge",
                extra={"req_id": req_id, "action_ref": action_ref, "oven_id": oven_id},
            )

            try:
                bridge_resp = requests.post(
                    f"{API_BASE_URL}/stackstorm/execute",
                    json={"action": action_ref, "parameters": parameters},
                    headers={"X-Request-ID": req_id},
                    timeout=30,
                )

                if bridge_resp.status_code == 200:
                    st2_data = bridge_resp.json()
                    st2_id = st2_data.get("id")

                    # Update task status with started timestamp
                    current_time = datetime.now(timezone.utc).isoformat()
                    requests.patch(
                        f"{API_BASE_URL}/ovens/{oven_id}",
                        json={
                            "processing_status": "processing",
                            "action_id": st2_id,
                            "started_at": current_time,
                        },
                        headers={"X-Request-ID": req_id},
                    )
                    logger.info(
                        "run_chef: Action with ref {action_ref} started successfully",
                        extra={
                            "req_id": req_id,
                            "st2_id": st2_id,
                            "started_at": current_time,
                            "oven_id": oven_id,
                        },
                    )
                else:
                    # Failed to execute - update error_message
                    error_msg = f"API Bridge failed: {bridge_resp.status_code} - {bridge_resp.text}"
                    logger.error(
                        "run_chef: API Bridge execution failed",
                        extra={
                            "req_id": req_id,
                            "oven_id": oven_id,
                            "status_code": bridge_resp.status_code,
                            "error_message": error_msg,
                        },
                    )
                    requests.patch(
                        f"{API_BASE_URL}/ovens/{oven_id}",
                        json={"processing_status": "failed", "error_message": error_msg},
                        headers={"X-Request-ID": req_id},
                    )

            except requests.exceptions.RequestException as e:
                # Network/timeout error - update error_message
                error_msg = f"Failed to reach API Bridge: {str(e)}"
                logger.error(
                    "run_chef: Failed to reach API Bridge",
                    extra={"req_id": req_id, "oven_id": oven_id, "error": str(e)},
                )
                try:
                    requests.patch(
                        f"{API_BASE_URL}/ovens/{oven_id}",
                        json={"processing_status": "failed", "error_message": error_msg},
                        headers={"X-Request-ID": req_id},
                        timeout=5,
                    )
                except Exception as update_error:
                    logger.error(
                        "run_chef: Could not update oven status after error",
                        extra={
                            "req_id": req_id,
                            "oven_id": oven_id,
                            "update_error": str(update_error),
                        },
                    )

        except Exception as e:
            logger.error(
                "run_chef: Chef loop encountered an error",
                extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
            )
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_chef()

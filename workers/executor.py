#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven Executor: Polls for pending Oven tasks calls /stackstorm/execute API"""

import os
import time
import requests
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Config: No ST2 keys required here!
API_BASE_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000/api/v1")
POLL_INTERVAL = int(os.getenv("OVEN_POLL_INTERVAL", "5"))

# System request ID for polling operations (distinguishes system calls from alert processing)
SYSTEM_REQ_ID = "SYSTEM-OVEN-POLL"


def wait_for_api():
    """Wait for API to be ready before starting main loop."""
    logger.info("Waiting for API to be ready: %s", API_BASE_URL)
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            resp = requests.get(f"{API_BASE_URL.rsplit('/api/v1', 1)[0]}/api/v1/health", timeout=5)
            if resp.status_code == 200:
                logger.info("API is ready! Starting executor...")
                return True
        except Exception:
            pass

        attempt += 1
        if attempt < max_attempts:
            time.sleep(2)

    logger.error("API did not become ready after %d attempts. Starting anyway...", max_attempts)
    return False


def run_executor():
    # Wait for API to be ready
    wait_for_api()

    logger.info("Oven Executor started. Target API: %s", API_BASE_URL)

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
                logger.error("[%s] No action_ref found for Oven ID %s", req_id, oven_id)
                time.sleep(POLL_INTERVAL)
                continue

            # Proxy the request through the API Bridge
            logger.info("[%s] Triggering %s via API bridge", req_id, action_ref)

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
                        "[%s] Action started. ST2 ID: %s at %s", req_id, st2_id, current_time
                    )
                else:
                    # Failed to execute - update error_message
                    error_msg = f"API Bridge failed: {bridge_resp.status_code} - {bridge_resp.text}"
                    logger.error("[%s] %s", req_id, error_msg)
                    requests.patch(
                        f"{API_BASE_URL}/ovens/{oven_id}",
                        json={"processing_status": "failed", "error_message": error_msg},
                        headers={"X-Request-ID": req_id},
                    )

            except requests.exceptions.RequestException as e:
                # Network/timeout error - update error_message
                error_msg = f"Failed to reach API Bridge: {str(e)}"
                logger.error("[%s] %s", req_id, error_msg)
                try:
                    requests.patch(
                        f"{API_BASE_URL}/ovens/{oven_id}",
                        json={"processing_status": "failed", "error_message": error_msg},
                        headers={"X-Request-ID": req_id},
                        timeout=5,
                    )
                except Exception:
                    logger.error("[%s] Could not update oven status after error", req_id)

        except Exception as e:
            logger.error("Executor loop encountered an error: %s", str(e))
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_executor()

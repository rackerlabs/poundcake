#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Chef: Polls for pending Oven tasks and executes them via StackStorm"""

import asyncio
import os
import time
from datetime import datetime, timezone

from api.core.logging import setup_logging, get_logger
from api.core.http_client import request_with_retry

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

# Config: No ST2 keys required here!
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
POLL_INTERVAL = int(os.getenv("OVEN_POLL_INTERVAL", "5"))
MAX_CONCURRENT_EXECUTIONS = int(os.getenv("OVEN_MAX_CONCURRENT_EXECUTIONS", "10"))
BATCH_LIMIT = int(os.getenv("OVEN_BATCH_LIMIT", str(MAX_CONCURRENT_EXECUTIONS)))

# System request ID for polling operations (distinguishes system calls from alert processing)
SYSTEM_REQ_ID = "SYSTEM-CHEF"


async def wait_for_api():
    """Wait for API to be ready before starting main loop."""
    logger.info(
        "Waiting for API to be ready",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL},
    )
    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            start_time = time.time()
            resp = await request_with_retry(
                "GET",
                f"{API_BASE_URL.rsplit('/api/v1', 1)[0]}/api/v1/health",
            )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                logger.info(
                    "API is ready! Starting chef...",
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
            await asyncio.sleep(2)

    logger.error(
        "API did not become ready. Starting anyway...",
        extra={"req_id": SYSTEM_REQ_ID, "max_attempts": max_attempts},
    )
    return False


async def _process_task(task: dict, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        oven_id = task["id"]
        req_id = task["req_id"]

        ingredient = task.get("ingredient", {})
        action_ref = ingredient.get("st2_action")
        parameters = ingredient.get("parameters", {})

        if not action_ref:
            logger.error(
                "No action_ref found for Oven",
                extra={"req_id": req_id, "oven_id": oven_id},
            )
            return

        logger.info(
            "Cooking action via API bridge",
            extra={"req_id": req_id, "action_ref": action_ref, "oven_id": oven_id},
        )

        try:
            start_time = time.time()
            bridge_resp = await request_with_retry(
                "POST",
                f"{API_BASE_URL}/stackstorm/execute",
                json={"action": action_ref, "parameters": parameters},
                headers={"X-Request-ID": req_id},
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if bridge_resp.status_code == 200:
                st2_data = bridge_resp.json()
                st2_id = st2_data.get("id")

                current_time = datetime.now(timezone.utc).isoformat()
                await request_with_retry(
                    "PATCH",
                    f"{API_BASE_URL}/ovens/{oven_id}",
                    json={
                        "processing_status": "processing",
                        "action_id": st2_id,
                        "started_at": current_time,
                    },
                    headers={"X-Request-ID": req_id},
                )
                logger.info(
                    "Action started successfully",
                    extra={
                        "req_id": req_id,
                        "st2_id": st2_id,
                        "started_at": current_time,
                        "oven_id": oven_id,
                        "method": "POST",
                        "status_code": bridge_resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
            else:
                error_msg = f"API Bridge failed: {bridge_resp.status_code} - {bridge_resp.text}"
                logger.error(
                    "API Bridge execution failed",
                    extra={
                        "req_id": req_id,
                        "oven_id": oven_id,
                        "method": "POST",
                        "status_code": bridge_resp.status_code,
                        "latency_ms": latency_ms,
                        "error_message": error_msg,
                    },
                )
                await request_with_retry(
                    "PATCH",
                    f"{API_BASE_URL}/ovens/{oven_id}",
                    json={"processing_status": "failed", "error_message": error_msg},
                    headers={"X-Request-ID": req_id},
                )

        except Exception as e:
            error_msg = f"Failed to reach API Bridge: {str(e)}"
            logger.error(
                "Failed to reach API Bridge",
                extra={"req_id": req_id, "oven_id": oven_id, "error": str(e)},
            )
            try:
                await request_with_retry(
                    "PATCH",
                    f"{API_BASE_URL}/ovens/{oven_id}",
                    json={"processing_status": "failed", "error_message": error_msg},
                    headers={"X-Request-ID": req_id},
                )
            except Exception as update_error:
                logger.error(
                    "Could not update oven status after error",
                    extra={
                        "req_id": req_id,
                        "oven_id": oven_id,
                        "update_error": str(update_error),
                    },
                )


async def run_chef():
    """Main chef loop - polls for oven tasks and executes them."""
    # Wait for API to be ready
    await wait_for_api()

    logger.info(
        "Chef started",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL, "poll_interval": POLL_INTERVAL},
    )

    while True:
        try:
            # Fetch next 'new' oven task
            start_time = time.time()
            resp = await request_with_retry(
                "GET",
                f"{API_BASE_URL}/ovens",
                params={"processing_status": "new", "limit": BATCH_LIMIT},
                headers={"X-Request-ID": SYSTEM_REQ_ID},
            )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch ovens",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                await asyncio.sleep(POLL_INTERVAL)
                continue
            tasks = resp.json()

            if not tasks:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)
            await asyncio.gather(*[_process_task(task, semaphore) for task in tasks])

        except Exception as e:
            logger.error(
                "Chef loop encountered an error",
                extra={"req_id": SYSTEM_REQ_ID, "error": str(e)},
            )
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_chef())

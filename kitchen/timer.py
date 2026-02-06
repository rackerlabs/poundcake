#!/usr/bin/env python3
#  ____                        _  ____      _
# |  _ \\ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \\| | | | '_ \\ / _` | |   / _` | |/ / _ \\
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \\___/ \\__,_|_| |_|\\__,_|\\____\\__,_|_|\\_\\___|
#
"""Timer Service - Monitors oven executions and updates completion status."""

import os
import time
from datetime import datetime, timezone
from api.core.logging import setup_logging, get_logger
from api.core.http_client import request_with_retry_sync

# Configuration
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000/api/v1").rstrip("/")
ST2_API_URL = os.getenv("ST2_API_URL", "http://stackstorm-api:9101/v1").rstrip("/")
TIMER_INTERVAL = int(os.getenv("TIMER_INTERVAL", "10"))
SLA_BUFFER = float(os.getenv("SLA_BUFFER_PERCENT", "0.2"))

ST2_API_KEY_FILE = "/app/config/st2_api_key"

# Configure Logging
setup_logging()
logger = get_logger("timer")


def get_st2_api_key():
    """Read ST2 API key from file."""
    try:
        if os.path.exists(ST2_API_KEY_FILE):
            with open(ST2_API_KEY_FILE, "r") as f:
                key = f.read().strip()
                if key:
                    return key
    except Exception:
        pass
    return os.getenv("ST2_API_KEY")


def update_oven(
    oven,
    req_id,
    status=None,
    st2_status=None,
    error_msg=None,
    final_status=False,
    action_result=None,
):
    """
    Centralized helper to update Oven records.
    Calculates actual_duration (int) based on started_at and now.
    Updates action_result with stackstorm results
    """
    oven_id = oven.get("id")
    payload = {}
    extra = {"req_id": req_id}

    if status:
        payload["processing_status"] = status
    if st2_status:
        payload["st2_status"] = st2_status
    if error_msg:
        payload["error_message"] = error_msg
    if action_result is not None:
        payload["action_result"] = action_result

    if final_status:
        now = datetime.now(timezone.utc)
        payload["processing_status"] = "complete"
        payload["completed_at"] = now.isoformat()

        # Calculate duration using started_at (fallback to created_at)
        start_str = oven.get("started_at") or oven.get("created_at")
        if start_str:
            # FIX: Convert string to aware datetime
            dt_obj = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if dt_obj.tzinfo is None:
                start_dt = dt_obj.replace(tzinfo=timezone.utc)
            else:
                start_dt = dt_obj

            duration = (now - start_dt).total_seconds()
            payload["actual_duration"] = int(duration)

    try:
        start_time = time.time()
        resp = request_with_retry_sync(
            "PUT",
            f"{POUNDCAKE_API_URL}/ovens/{oven_id}",
            json=payload,
            headers={"X-Request-ID": req_id},
            timeout=10,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        resp.raise_for_status()
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        extra.update({"method": "PUT", "latency_ms": latency_ms})
        if "resp" in locals():
            extra["status_code"] = resp.status_code
        logger.error(f"Failed to update Oven {oven_id}: {e}", extra=extra)
        return False


def cancel_st2_execution(action_id, req_id):
    """Instructs StackStorm to stop an execution."""
    api_key = get_st2_api_key()
    try:
        start_time = time.time()
        resp = request_with_retry_sync(
            "DELETE",
            f"{ST2_API_URL}/executions/{action_id}",
            headers={"St2-Api-Key": api_key, "X-Request-ID": req_id},
            timeout=10,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"Error canceling ST2 action {action_id}: {e}",
            extra={
                "req_id": req_id,
                "method": "DELETE",
                "latency_ms": latency_ms,
                "status_code": resp.status_code if "resp" in locals() else None,
            },
        )
    return False


def check_for_timeouts(oven, req_id):
    """
    Evaluates timeouts.
    SLA Warning: expected_duration * (1 + buffer)
    Hard Timeout: expected_duration * 5 (Safety net)
    """
    created_at_str = oven.get("created_at")
    if not created_at_str:
        return False

    # Ensure the string is interpreted correctly
    # and force it to be UTC aware
    dt_obj = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    if dt_obj.tzinfo is None:
        created_at = dt_obj.replace(tzinfo=timezone.utc)
    else:
        created_at = dt_obj

    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()

    expected = oven.get("expected_duration") or 60
    sla_threshold = expected * (1 + SLA_BUFFER)
    hard_timeout = expected * 5
    extra = {"req_id": req_id}

    # Hard Timeout Check
    if elapsed > hard_timeout:
        logger.critical(
            f"Oven {oven['id']} exceeded safety timeout ({int(elapsed)}s). Killing.", extra=extra
        )
        cancel_st2_execution(oven.get("action_id"), req_id)
        update_oven(
            oven,
            req_id,
            st2_status="timeout",
            error_msg=f"Task killed: elapsed time {int(elapsed)}s exceeded 5x expected duration",
            final_status=True,
        )
        return True

    # SLA Warning Check
    if elapsed > sla_threshold:
        logger.warning(
            f"Oven {oven['id']} running past SLA buffer ({int(elapsed)}s > {int(sla_threshold)}s)",
            extra=extra,
        )

    return False


def monitor_ovens():
    """Polls for processing ovens and updates terminal states."""
    try:
        start_time = time.time()
        resp = request_with_retry_sync(
            "GET",
            f"{POUNDCAKE_API_URL}/ovens",
            params={"processing_status": "processing"},
            timeout=10,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        if resp.status_code != 200:
            logger.error(
                "Failed to fetch processing ovens",
                extra={
                    "req_id": "SYSTEM",
                    "method": "GET",
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                },
            )
            return
        ovens = resp.json()

        for oven in ovens:
            req_id = oven.get("req_id", "SYSTEM")
            action_id = oven.get("action_id")
            extra = {"req_id": req_id}

            # Check Timing / SLA
            if check_for_timeouts(oven, req_id):
                continue

            # Sync with StackStorm
            if not action_id:
                continue

            api_key = get_st2_api_key()
            st2_start_time = time.time()
            st2_resp = request_with_retry_sync(
                "GET",
                f"{ST2_API_URL}/executions/{action_id}",
                headers={"St2-Api-Key": api_key, "X-Request-ID": req_id},
                timeout=10,
            )
            st2_latency_ms = int((time.time() - st2_start_time) * 1000)

            if st2_resp.status_code == 200:
                st2_data = st2_resp.json()
                st2_status = st2_data.get("status")
                st2_action_results = st2_data.get("result", {})

                if st2_status in ["succeeded", "failed", "canceled", "timeout"]:
                    err = None
                    if st2_status == "failed":
                        err = st2_action_results.get("error") or "StackStorm execution failed"

                    update_oven(
                        oven,
                        req_id,
                        st2_status=st2_status,
                        error_msg=err,
                        final_status=True,
                        action_result=st2_action_results,
                    )
                    logger.info(
                        f"Oven {oven['id']} finalized with ST2 status: {st2_status}",
                        extra={
                            **extra,
                            "method": "GET",
                            "status_code": st2_resp.status_code,
                            "latency_ms": st2_latency_ms,
                        },
                    )

            elif st2_resp.status_code == 404:
                extra.update(
                    {
                        "method": "GET",
                        "status_code": st2_resp.status_code,
                        "latency_ms": st2_latency_ms,
                    }
                )
                logger.error(f"Oven {oven['id']} action {action_id} not found in ST2.", extra=extra)
                update_oven(
                    oven,
                    req_id,
                    st2_status="abandoned",
                    error_msg="ST2 ID not found",
                    final_status=True,
                )
            else:
                logger.error(
                    f"Oven {oven['id']} action {action_id} returned unexpected status from ST2",
                    extra={
                        **extra,
                        "method": "GET",
                        "status_code": st2_resp.status_code,
                        "latency_ms": st2_latency_ms,
                    },
                )

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"Error in monitor loop: {str(e)}",
            extra={"req_id": "SYSTEM", "method": "GET", "latency_ms": latency_ms},
        )


def wait_for_api():
    logger.info("Waiting for API health check...", extra={"req_id": "SYSTEM"})
    while True:
        try:
            start_time = time.time()
            resp = request_with_retry_sync(
                "GET",
                f"{POUNDCAKE_API_URL}/health",
                timeout=5,
            )
            latency_ms = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                logger.info(
                    "API health check passed",
                    extra={
                        "req_id": "SYSTEM",
                        "method": "GET",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return True
        except Exception:
            pass
        time.sleep(2)


if __name__ == "__main__":
    wait_for_api()
    logger.info(
        f"Timer started. Interval: {TIMER_INTERVAL}s, SLA Buffer: {int(SLA_BUFFER*100)}%",
        extra={"req_id": "SYSTEM"},
    )
    while True:
        monitor_ovens()
        time.sleep(TIMER_INTERVAL)

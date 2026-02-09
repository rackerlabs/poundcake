#!/usr/bin/env python3
#  ____                        _  ____      _
# |  _ \\ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \\| | | | '_ \\ / _` | |   / _` | |/ / _ \\
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \\___/ \\__,_|_| |_|\\__,_|\\____\\__,_|_|\\_\\___|
#
"""Timer Service - Monitors dish executions and updates completion status."""

import os
import time
from typing import Any, Optional
import httpx
from datetime import datetime, timezone
from api.core.logging import setup_logging, get_logger
from api.core.statuses import ST2_TERMINAL_STATUSES, ST2_FAILURE_STATUSES
from kitchen.service_helpers import wait_for_api

# Configuration
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://api:8000").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
TIMER_INTERVAL = int(os.getenv("TIMER_INTERVAL", "10"))
SLA_BUFFER = float(os.getenv("SLA_BUFFER_PERCENT", "0.2"))

# Configure Logging
setup_logging()
logger = get_logger("timer")


def update_dish(
    dish: dict[str, Any],
    req_id: str,
    processing_status: Optional[str] = None,
    status: Optional[str] = None,
    error_msg: Optional[str] = None,
    final_status: bool = False,
    result: Optional[Any] = None,
    started_at: Optional[str] = None,
) -> bool:
    """
    Centralized helper to update Dish records.
    Calculates actual_duration_sec based on started_at and now.
    """
    dish_id = dish.get("id")
    payload = {}
    extra = {"req_id": req_id}

    if processing_status:
        payload["processing_status"] = processing_status
    if status:
        payload["status"] = status
    if error_msg:
        payload["error_message"] = error_msg
    if result is not None:
        payload["result"] = result
    if started_at:
        payload["started_at"] = started_at

    if final_status:
        now = datetime.now(timezone.utc)
        payload["completed_at"] = now.isoformat()

        start_str = dish.get("started_at") or dish.get("created_at")
        if start_str:
            dt_obj = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if dt_obj.tzinfo is None:
                start_dt = dt_obj.replace(tzinfo=timezone.utc)
            else:
                start_dt = dt_obj

            duration = (now - start_dt).total_seconds()
            payload["actual_duration_sec"] = int(duration)

    try:
        start_time = time.time()
        with httpx.Client(timeout=10) as client:
            resp = client.put(
                f"{API_BASE_URL}/dishes/{dish_id}",
                json=payload,
                headers={"X-Request-ID": req_id},
            )
        latency_ms = int((time.time() - start_time) * 1000)
        resp.raise_for_status()
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        extra.update({"method": "PUT", "latency_ms": latency_ms})
        if "resp" in locals():
            extra["status_code"] = resp.status_code
        logger.error(f"Failed to update Dish {dish_id}: {e}", extra=extra)
        return False


def cancel_execution(execution_id: str, req_id: str) -> bool:
    """Instructs API to stop an execution."""
    try:
        start_time = time.time()
        with httpx.Client(timeout=10) as client:
            resp = client.put(
                f"{API_BASE_URL}/cook/executions/{execution_id}",
                headers={"X-Request-ID": req_id},
            )
        latency_ms = int((time.time() - start_time) * 1000)
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"Error canceling ST2 execution {execution_id}: {e}",
            extra={
                "req_id": req_id,
                "method": "PUT",
                "latency_ms": latency_ms,
                "status_code": resp.status_code if "resp" in locals() else None,
            },
        )
    return False


def check_for_timeouts(dish: dict[str, Any], req_id: str) -> None:
    """
    Evaluates timeouts.
    SLA Warning: expected_duration_sec * (1 + buffer)
    Hard Timeout: expected_duration_sec * 5 (Safety net)
    """
    started_at_str = dish.get("started_at") or dish.get("created_at")
    if not started_at_str:
        return False

    dt_obj = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
    if dt_obj.tzinfo is None:
        created_at = dt_obj.replace(tzinfo=timezone.utc)
    else:
        created_at = dt_obj

    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()

    expected = dish.get("expected_duration_sec") or 60
    sla_threshold = expected * (1 + SLA_BUFFER)
    hard_timeout = expected * 5
    extra = {"req_id": req_id}

    if elapsed > hard_timeout:
        logger.critical(
            f"Dish {dish['id']} exceeded safety timeout ({int(elapsed)}s). Killing.", extra=extra
        )
        cancel_execution(dish.get("workflow_execution_id"), req_id)
        update_dish(
            dish,
            req_id,
            processing_status="failed",
            status="timeout",
            error_msg=f"Task killed: elapsed time {int(elapsed)}s exceeded 5x expected duration",
            final_status=True,
        )
        return True

    if elapsed > sla_threshold:
        logger.warning(
            f"Dish {dish['id']} running past SLA buffer ({int(elapsed)}s > {int(sla_threshold)}s)",
            extra=extra,
        )

    return False


def monitor_dishes() -> None:
    """Polls for processing dishes and updates terminal states."""
    try:
        start_time = time.time()
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{API_BASE_URL}/dishes",
                params={"processing_status": "processing"},
            )
        latency_ms = int((time.time() - start_time) * 1000)
        if resp.status_code != 200:
            logger.error(
                "Failed to fetch processing dishes",
                extra={
                    "req_id": "SYSTEM",
                    "method": "GET",
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                },
            )
            return
        dishes = resp.json()

        for dish in dishes:
            req_id = dish.get("req_id", "SYSTEM")
            execution_id = dish.get("workflow_execution_id")
            extra = {"req_id": req_id}

            if check_for_timeouts(dish, req_id):
                continue

            if not execution_id:
                continue

            st2_start_time = time.time()
            with httpx.Client(timeout=10) as client:
                st2_resp = client.get(
                    f"{API_BASE_URL}/cook/executions/{execution_id}",
                    headers={"X-Request-ID": req_id},
                )
            st2_latency_ms = int((time.time() - st2_start_time) * 1000)

            if st2_resp.status_code == 200:
                st2_data = st2_resp.json()
                st2_status = st2_data.get("status")
                st2_action_results = st2_data.get("result", {})
                dish_result = st2_action_results
                tasks_result = None
                if isinstance(st2_action_results, dict) and "tasks" in st2_action_results:
                    tasks_result = st2_action_results["tasks"]
                else:
                    # Fetch tasks explicitly if not included in execution result
                    try:
                        with httpx.Client(timeout=10) as client:
                            tasks_resp = client.get(
                                f"{API_BASE_URL}/cook/executions/{execution_id}/tasks",
                                headers={"X-Request-ID": req_id},
                            )
                        if tasks_resp.status_code == 200:
                            tasks_result = tasks_resp.json()
                    except Exception:
                        tasks_result = None

                # If tasks lack timestamps, prefer child execution list for richer details
                def _tasks_missing_timestamps(tasks: Any) -> bool:
                    if not isinstance(tasks, list) or not tasks:
                        return True
                    for task in tasks:
                        if not isinstance(task, dict):
                            continue
                        if task.get("start_timestamp") or task.get("end_timestamp"):
                            return False
                    return True

                def _sort_tasks_by_execution(tasks: Any) -> Any:
                    if not isinstance(tasks, list):
                        return tasks

                    def _key(item: Any) -> tuple[str, str]:
                        if not isinstance(item, dict):
                            return ("", "")
                        start_ts = item.get("start_timestamp") or item.get("end_timestamp") or ""
                        end_ts = item.get("end_timestamp") or ""
                        return (start_ts, end_ts)

                    return sorted(tasks, key=_key)

                if _tasks_missing_timestamps(tasks_result):
                    try:
                        with httpx.Client(timeout=10) as client:
                            children_resp = client.get(
                                f"{API_BASE_URL}/cook/executions",
                                params={"parent": execution_id, "limit": 1000},
                                headers={"X-Request-ID": req_id},
                            )
                        if children_resp.status_code == 200:
                            children = children_resp.json()
                            tasks_result = _sort_tasks_by_execution(
                                [
                                    {
                                        "id": child.get("id"),
                                        "task_id": (
                                            child.get("context", {})
                                            .get("orquesta", {})
                                            .get("task_id")
                                        ),
                                        "status": child.get("status"),
                                        "result": child.get("result"),
                                        "start_timestamp": child.get("start_timestamp"),
                                        "end_timestamp": child.get("end_timestamp"),
                                    }
                                    for child in children
                                ]
                            )
                    except Exception:
                        pass

                if tasks_result is None:
                    # Fallback: fetch child executions by parent id and store results
                    try:
                        with httpx.Client(timeout=10) as client:
                            children_resp = client.get(
                                f"{API_BASE_URL}/cook/executions",
                                params={"parent": execution_id, "limit": 1000},
                                headers={"X-Request-ID": req_id},
                            )
                        if children_resp.status_code == 200:
                            children = children_resp.json()
                            tasks_result = _sort_tasks_by_execution(
                                [
                                    {
                                        "id": child.get("id"),
                                        "task_id": (
                                            child.get("context", {})
                                            .get("orquesta", {})
                                            .get("task_id")
                                        ),
                                        "status": child.get("status"),
                                        "result": child.get("result"),
                                        "start_timestamp": child.get("start_timestamp"),
                                        "end_timestamp": child.get("end_timestamp"),
                                    }
                                    for child in children
                                ]
                            )
                    except Exception:
                        tasks_result = None

                tasks_result = _sort_tasks_by_execution(tasks_result)

                dish_started_at = None
                if tasks_result is not None:
                    # Store full tasks list for later inspection
                    dish_result = tasks_result

                    # If dish.started_at is not set, use earliest task start timestamp
                    dish_started_at = None
                    for task in tasks_result:
                        if not isinstance(task, dict):
                            continue
                        ts = task.get("start_timestamp")
                        if ts:
                            if dish_started_at is None or ts < dish_started_at:
                                dish_started_at = ts

                    # Persist per-task execution details
                    try:
                        items = []
                        existing_status = {}
                        try:
                            with httpx.Client(timeout=10) as client:
                                ing_resp = client.get(
                                    f"{API_BASE_URL}/dishes/{dish.get('id')}/ingredients",
                                    headers={"X-Request-ID": req_id},
                                )
                            if ing_resp.status_code == 200:
                                for ing in ing_resp.json():
                                    key = (
                                        ing.get("task_id") or "",
                                        ing.get("st2_execution_id"),
                                    )
                                    existing_status[key] = ing.get("status")
                        except Exception:
                            existing_status = {}

                        for task in tasks_result:
                            if not isinstance(task, dict):
                                continue
                            status = task.get("status")
                            cache_key = (task.get("task_id") or "", task.get("id"))
                            prev_status = existing_status.get(cache_key)
                            if prev_status != status:
                                logger.debug(
                                    "Task status changed",
                                    extra={
                                        "req_id": req_id,
                                        "dish_id": dish.get("id"),
                                        "task_id": task.get("task_id"),
                                        "status": status,
                                    },
                                )

                            items.append(
                                {
                                    "st2_execution_id": task.get("id"),
                                    "task_id": task.get("task_id"),
                                    "status": status,
                                    "started_at": task.get("start_timestamp")
                                    or dish.get("created_at"),
                                    "completed_at": task.get("end_timestamp"),
                                    "result": task.get("result"),
                                }
                            )

                        if items:
                            with httpx.Client(timeout=10) as client:
                                client.post(
                                    f"{API_BASE_URL}/dishes/{dish.get('id')}/ingredients/bulk",
                                    json={"items": items},
                                    headers={"X-Request-ID": req_id},
                                )
                    except Exception:
                        pass

                if st2_status in ST2_TERMINAL_STATUSES:
                    err = None
                    processing_status = "complete"
                    if st2_status in ST2_FAILURE_STATUSES:
                        processing_status = "failed"
                        err = st2_action_results.get("error") or "StackStorm execution failed"

                    update_dish(
                        dish,
                        req_id,
                        processing_status=processing_status,
                        status="completed",
                        error_msg=err,
                        final_status=True,
                        result=dish_result,
                        started_at=dish_started_at or dish.get("started_at"),
                    )
                    logger.info(
                        f"Dish {dish['id']} finalized with ST2 status: {st2_status}",
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
                logger.error(
                    f"Dish {dish['id']} execution {execution_id} not found in ST2.", extra=extra
                )
                update_dish(
                    dish,
                    req_id,
                    processing_status="failed",
                    status="abandoned",
                    error_msg="ST2 execution not found",
                    final_status=True,
                )
            else:
                logger.error(
                    f"Dish {dish['id']} execution {execution_id} returned unexpected status from ST2",
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


if __name__ == "__main__":
    wait_for_api(API_BASE_URL, "SYSTEM", logger)
    logger.info(
        f"Timer started. Interval: {TIMER_INTERVAL}s, SLA Buffer: {int(SLA_BUFFER*100)}%",
        extra={"req_id": "SYSTEM"},
    )
    while True:
        monitor_dishes()
        time.sleep(TIMER_INTERVAL)

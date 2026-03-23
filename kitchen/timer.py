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

from api.core.http_client import request_with_retry_sync
from datetime import datetime, timezone
from api.core.logging import setup_logging, get_logger
from api.core.config import get_settings
from api.core.statuses import ST2_TERMINAL_STATUSES, ST2_FAILURE_STATUSES
from kitchen.execution_segments import next_pending_execution_segment
from kitchen.service_helpers import wait_for_api, get_service_headers

# Configuration
POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://poundcake:8080").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
TIMER_INTERVAL = int(os.getenv("TIMER_INTERVAL", "10"))
POLL_LIMIT = int(os.getenv("TIMER_LIMIT", "1"))
SLA_BUFFER = float(os.getenv("SLA_BUFFER_PERCENT", "0.2"))
SUPPRESSION_LIFECYCLE_INTERVAL = int(os.getenv("SUPPRESSION_LIFECYCLE_INTERVAL", "30"))

# Configure Logging
setup_logging()
logger = get_logger("timer")
POLLER_RETRIES = get_settings().poller_http_retries
SYSTEM_REQ_ID = "SYSTEM-TIMER"
MISSING_EXECUTION_TIMEOUT_SECONDS = get_settings().chef_missing_execution_timeout_seconds
MISSING_WORKFLOW_PATH_FRAGMENT = "/opt/stackstorm/packs/poundcake/actions/workflows/"
API_UNAVAILABLE_SINCE: float | None = None
LAST_SUPPRESSION_LIFECYCLE_RUN = 0.0


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _task_execution_ref(task: dict[str, Any]) -> str | None:
    execution_ref = task.get("id")
    if execution_ref:
        return str(execution_ref)

    action_executions = task.get("action_executions")
    if isinstance(action_executions, list):
        for action_execution in action_executions:
            if not isinstance(action_execution, dict):
                continue
            execution_ref = action_execution.get("id") or action_execution.get("execution_id")
            if execution_ref:
                return str(execution_ref)
    return None


def _task_key(task: dict[str, Any], fallback_key: str | None = None) -> str | None:
    task_key = (
        task.get("task_key")
        or task.get("task_id")
        or task.get("name")
        or (task.get("context", {}).get("orquesta", {}).get("task_id"))
        or fallback_key
    )
    if task_key is None:
        return None
    return str(task_key)


def _normalize_tasks(tasks_payload: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(tasks_payload, dict):
        if isinstance(tasks_payload.get("tasks"), list):
            tasks_payload = tasks_payload.get("tasks")
        else:
            for key, value in tasks_payload.items():
                if not isinstance(value, dict):
                    continue
                normalized.append(
                    {
                        "id": _task_execution_ref(value),
                        "task_key": _task_key(value, str(key)),
                        "status": value.get("status") or value.get("state"),
                        "result": value.get("result"),
                        "start_timestamp": value.get("start_timestamp"),
                        "end_timestamp": value.get("end_timestamp"),
                    }
                )
            return normalized

    if not isinstance(tasks_payload, list):
        return normalized

    for task in tasks_payload:
        if not isinstance(task, dict):
            continue
        normalized.append(
            {
                "id": _task_execution_ref(task),
                "task_key": _task_key(task),
                "status": task.get("status") or task.get("state"),
                "result": task.get("result"),
                "start_timestamp": task.get("start_timestamp"),
                "end_timestamp": task.get("end_timestamp"),
            }
        )
    return normalized


def update_dish(
    dish: dict[str, Any],
    req_id: str,
    processing_status: Optional[str] = None,
    execution_status: Optional[str] = None,
    error_msg: Optional[str] = None,
    execution_ref: Optional[str] = None,
    retry_attempt: Optional[int] = None,
    clear_error: bool = False,
    final_status: bool = False,
    result: Optional[Any] = None,
    started_at: Optional[str] = None,
) -> bool:
    """
    Centralized helper to update Dish records.
    Calculates actual_duration_sec based on started_at and now.
    """
    dish_id = dish.get("id")
    payload: dict[str, Any] = {}
    extra: dict[str, Any] = {"req_id": req_id}

    if processing_status:
        payload["processing_status"] = processing_status
    if execution_status:
        payload["execution_status"] = execution_status
    if clear_error:
        payload["error_message"] = None
    elif error_msg is not None:
        payload["error_message"] = error_msg
    if execution_ref is not None:
        payload["execution_ref"] = execution_ref
    if retry_attempt is not None:
        payload["retry_attempt"] = retry_attempt
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
        resp = request_with_retry_sync(
            "PUT",
            f"{API_BASE_URL}/dishes/{dish_id}",
            json=payload,
            headers=get_service_headers(req_id),
            timeout=10,
            retries=POLLER_RETRIES,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        resp.raise_for_status()
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        extra.update({"method": "PUT", "latency_ms": latency_ms})
        if "resp" in locals():
            extra["status_code"] = resp.status_code
        extra.update({"dish_id": dish_id, "error": str(e)})
        logger.error("Failed to update dish", extra=extra)
        return False


def _is_missing_workflow_file_error(error_message: Any) -> bool:
    if not isinstance(error_message, str):
        return False
    return (
        "No such file or directory" in error_message
        and MISSING_WORKFLOW_PATH_FRAGMENT in error_message
    )


def _maybe_retry_missing_workflow_execution(
    dish: dict[str, Any], req_id: str, error_message: Any
) -> tuple[bool, str | None]:
    if not _is_missing_workflow_file_error(error_message):
        return False, None

    retry_attempt = int(dish.get("retry_attempt") or 0)
    if retry_attempt != 0:
        return False, None
    return False, "retry skipped: recipe-level workflow metadata no longer exists"


def _mark_pending_ingredients_failed(dish_id: int, req_id: str, error_message: str) -> None:
    """Backfill pending ingredient rows to failed for terminal workflow failures."""
    try:
        ingredients_resp = request_with_retry_sync(
            "GET",
            f"{API_BASE_URL}/dishes/{dish_id}/ingredients",
            headers=get_service_headers(req_id),
            timeout=10,
            retries=POLLER_RETRIES,
        )
        if ingredients_resp.status_code != 200:
            return

        ingredients = ingredients_resp.json() or []
        failed_at = datetime.now(timezone.utc).isoformat()
        pending_statuses = {"pending", "running", "processing", "queued", None}
        items = []
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue
            if ingredient.get("execution_status") not in pending_statuses:
                continue
            if ingredient.get("completed_at"):
                continue

            recipe_ingredient_id = ingredient.get("recipe_ingredient_id")
            task_key = ingredient.get("task_key")
            if recipe_ingredient_id is None and not task_key:
                continue

            items.append(
                {
                    "recipe_ingredient_id": recipe_ingredient_id,
                    "task_key": task_key,
                    "execution_status": "failed",
                    "completed_at": failed_at,
                    "error_message": error_message,
                }
            )

        if not items:
            return

        request_with_retry_sync(
            "POST",
            f"{API_BASE_URL}/dishes/{dish_id}/ingredients/bulk",
            json={"items": items},
            headers=get_service_headers(req_id),
            timeout=10,
            retries=POLLER_RETRIES,
        )
    except Exception as exc:
        logger.warning(
            "Failed to backfill pending dish ingredients after workflow failure",
            extra={"req_id": req_id, "dish_id": dish_id, "error": str(exc)},
        )


def _fetch_dish_ingredients(dish_id: int, req_id: str) -> list[dict[str, Any]]:
    ingredients_resp = request_with_retry_sync(
        "GET",
        f"{API_BASE_URL}/dishes/{dish_id}/ingredients",
        headers=get_service_headers(req_id),
        timeout=10,
        retries=POLLER_RETRIES,
    )
    if ingredients_resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch dish ingredients: {ingredients_resp.text}")
    payload = ingredients_resp.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _requeue_dish_for_next_segment(
    dish: dict[str, Any],
    req_id: str,
    *,
    result: Any | None = None,
    started_at: str | None = None,
) -> bool:
    dish_id = dish.get("id")
    payload: dict[str, Any] = {
        "processing_status": "new",
        "execution_status": None,
        "execution_ref": None,
        "error_message": None,
    }
    if result is not None:
        payload["result"] = result
    if started_at:
        payload["started_at"] = started_at
    try:
        resp = request_with_retry_sync(
            "PATCH",
            f"{API_BASE_URL}/dishes/{dish_id}",
            json=payload,
            headers=get_service_headers(req_id),
            timeout=10,
            retries=POLLER_RETRIES,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to requeue dish for next execution segment",
            extra={"req_id": req_id, "dish_id": dish_id, "error": str(exc)},
        )
        return False


def _execute_pending_bakery_ingredients(
    dish: dict[str, Any],
    req_id: str,
    *,
    ingredients: list[dict[str, Any]] | None = None,
    segment: list[dict[str, Any]] | None = None,
) -> tuple[bool, str | None, bool]:
    """Execute pending Bakery ingredients for a dish and persist per-step state."""
    dish_id = dish.get("id")
    if not dish_id:
        return True, None, False
    try:
        current_ingredients = ingredients or _fetch_dish_ingredients(int(dish_id), req_id)
        pending_bakery = segment
        if pending_bakery is None:
            next_segment = next_pending_execution_segment(dish, current_ingredients)
            if next_segment is None or next_segment[0] != "bakery":
                return True, None, False
            pending_bakery = next_segment[1]
        if not pending_bakery:
            return True, None, False

        on_failure_by_ri_id: dict[int, str] = {}
        recipe = dish.get("recipe")
        if isinstance(recipe, dict):
            ri_items = recipe.get("recipe_ingredients")
            if isinstance(ri_items, list):
                for ri in ri_items:
                    if not isinstance(ri, dict):
                        continue
                    ri_id = ri.get("id")
                    ingredient = ri.get("ingredient")
                    if not isinstance(ingredient, dict) or not isinstance(ri_id, int):
                        continue
                    on_failure_by_ri_id[ri_id] = str(ingredient.get("on_failure") or "stop").lower()

        for item in pending_bakery:
            recipe_ingredient_id = _coerce_int(item.get("recipe_ingredient_id"))
            task_key = item.get("task_key")
            start_ts = datetime.now(timezone.utc).isoformat()
            request_with_retry_sync(
                "POST",
                f"{API_BASE_URL}/dishes/{dish_id}/ingredients/bulk",
                json={
                    "items": [
                        {
                            "recipe_ingredient_id": recipe_ingredient_id,
                            "task_key": task_key,
                            "execution_engine": "bakery",
                            "execution_target": item.get("execution_target"),
                            "destination_target": item.get("destination_target"),
                            "execution_status": "running",
                            "started_at": start_ts,
                        }
                    ]
                },
                headers=get_service_headers(req_id),
                timeout=10,
                retries=POLLER_RETRIES,
            )
            exec_resp = request_with_retry_sync(
                "POST",
                f"{API_BASE_URL}/cook/execute",
                json={
                    "execution_engine": "bakery",
                    "execution_target": item.get("execution_target"),
                    "execution_payload": item.get("execution_payload") or {},
                    "execution_parameters": item.get("execution_parameters") or {},
                    "context": {
                        "order_id": dish.get("order_id"),
                        "recipe_ingredient_id": recipe_ingredient_id,
                        "destination_target": item.get("destination_target") or "",
                    },
                },
                headers=get_service_headers(req_id),
                timeout=30,
                retries=POLLER_RETRIES,
            )

            success = False
            error_message = None
            execution_ref = None
            result_payload = None
            if exec_resp.status_code in (200, 201):
                body = exec_resp.json()
                success = str(body.get("status") or "") == "succeeded"
                execution_ref = body.get("execution_ref")
                result_payload = body.get("raw") or body.get("result")
                if not success:
                    error_message = str(body.get("error_message") or "Bakery execution failed")
            else:
                error_message = str(exec_resp.text)

            request_with_retry_sync(
                "POST",
                f"{API_BASE_URL}/dishes/{dish_id}/ingredients/bulk",
                json={
                    "items": [
                        {
                            "recipe_ingredient_id": recipe_ingredient_id,
                            "task_key": task_key,
                            "execution_engine": "bakery",
                            "execution_target": item.get("execution_target"),
                            "destination_target": item.get("destination_target"),
                            "execution_ref": execution_ref,
                            "execution_status": "succeeded" if success else "failed",
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "result": result_payload if isinstance(result_payload, dict) else None,
                            "error_message": error_message,
                        }
                    ]
                },
                headers=get_service_headers(req_id),
                timeout=10,
                retries=POLLER_RETRIES,
            )

            on_failure = (
                on_failure_by_ri_id.get(recipe_ingredient_id, "stop")
                if recipe_ingredient_id is not None
                else "stop"
            )
            if not success and on_failure != "continue":
                return False, error_message, True

        return True, None, True
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), True


def cancel_execution(execution_id: str, req_id: str) -> bool:
    """Instructs API to stop an execution."""
    try:
        start_time = time.time()
        resp = request_with_retry_sync(
            "PUT",
            f"{API_BASE_URL}/cook/executions/{execution_id}",
            headers=get_service_headers(req_id),
            timeout=10,
            retries=POLLER_RETRIES,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        resp.raise_for_status()
        return True
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "Error canceling ST2 execution",
            extra={
                "req_id": req_id,
                "method": "PUT",
                "latency_ms": latency_ms,
                "status_code": resp.status_code if "resp" in locals() else None,
                "execution_id": execution_id,
                "error": str(e),
            },
        )
    return False


def check_for_timeouts(dish: dict[str, Any], req_id: str) -> bool:
    """
    Evaluates timeouts.
    SLA Warning: expected_duration_sec * (1 + buffer)
    Hard Timeout: expected_duration_sec * 5 (Safety net)
    Returns True if dish timed out and was cancelled.
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
    extra: dict[str, Any] = {"req_id": req_id}

    if elapsed > hard_timeout:
        extra.update(
            {
                "dish_id": dish["id"],
                "elapsed_sec": int(elapsed),
                "hard_timeout_sec": int(hard_timeout),
            }
        )
        logger.critical("Dish exceeded safety timeout; killing execution", extra=extra)
        exec_id = dish.get("execution_ref")
        if exec_id:
            cancel_execution(exec_id, req_id)
        update_dish(
            dish,
            req_id,
            processing_status="failed",
            execution_status="timeout",
            error_msg=f"Task killed: elapsed time {int(elapsed)}s exceeded 5x expected duration",
            final_status=True,
        )
        return True

    if elapsed > sla_threshold:
        extra.update(
            {
                "dish_id": dish["id"],
                "elapsed_sec": int(elapsed),
                "sla_threshold_sec": int(sla_threshold),
            }
        )
        logger.warning("Dish running past SLA buffer", extra=extra)

    return False


def monitor_dishes() -> None:
    """Polls for processing dishes and updates terminal states."""
    global API_UNAVAILABLE_SINCE
    try:
        dishes: list[dict[str, Any]] = []
        for status in ("processing", "finalizing"):
            start_time = time.time()
            resp = request_with_retry_sync(
                "GET",
                f"{API_BASE_URL}/dishes",
                params={"processing_status": status, "limit": POLL_LIMIT},
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
                        "processing_status": status,
                    },
                )
                continue

            if API_UNAVAILABLE_SINCE is not None:
                downtime_sec = int(time.time() - API_UNAVAILABLE_SINCE)
                logger.info(
                    "Timer API connectivity restored",
                    extra={"req_id": SYSTEM_REQ_ID, "downtime_sec": downtime_sec},
                )
                API_UNAVAILABLE_SINCE = None
            dishes.extend(resp.json())

        for dish in dishes:
            req_id = dish.get("req_id", SYSTEM_REQ_ID)
            execution_id = dish.get("execution_ref")
            extra: dict[str, Any] = {"req_id": req_id}

            claim_resp = request_with_retry_sync(
                "POST",
                f"{API_BASE_URL}/dishes/{dish.get('id')}/finalize-claim",
                headers=get_service_headers(req_id),
                timeout=10,
                retries=POLLER_RETRIES,
            )
            if claim_resp.status_code == 409:
                continue
            if claim_resp.status_code != 200:
                logger.error(
                    "Failed to claim dish for finalization",
                    extra={
                        "req_id": req_id,
                        "dish_id": dish.get("id"),
                        "status_code": claim_resp.status_code,
                    },
                )
                continue
            dish = claim_resp.json()
            execution_id = dish.get("execution_ref")

            if check_for_timeouts(dish, req_id):
                continue

            if not execution_id:
                try:
                    ingredients_payload = _fetch_dish_ingredients(int(dish["id"]), req_id)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to fetch dish ingredients for no-execution recovery",
                        extra={"req_id": req_id, "dish_id": dish.get("id"), "error": str(exc)},
                    )
                    continue

                next_segment = next_pending_execution_segment(dish, ingredients_payload)
                if next_segment is None:
                    update_dish(
                        dish,
                        req_id,
                        processing_status="complete",
                        execution_status="succeeded",
                        final_status=True,
                    )
                    continue

                if next_segment[0] == "bakery":
                    bakery_ok, bakery_err, _ = _execute_pending_bakery_ingredients(
                        dish,
                        req_id,
                        ingredients=ingredients_payload,
                        segment=next_segment[1],
                    )
                    if not bakery_ok:
                        update_dish(
                            dish,
                            req_id,
                            processing_status="failed",
                            execution_status="failed",
                            error_msg=bakery_err,
                            final_status=True,
                        )
                        continue

                    refreshed_ingredients = _fetch_dish_ingredients(int(dish["id"]), req_id)
                    if next_pending_execution_segment(dish, refreshed_ingredients) is None:
                        update_dish(
                            dish,
                            req_id,
                            processing_status="complete",
                            execution_status="succeeded",
                            final_status=True,
                        )
                    else:
                        _requeue_dish_for_next_segment(dish, req_id)
                    continue

                start_str = dish.get("started_at") or dish.get("created_at")
                if start_str:
                    dt_obj = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    if dt_obj.tzinfo is None:
                        start_dt = dt_obj.replace(tzinfo=timezone.utc)
                    else:
                        start_dt = dt_obj
                    elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
                    if elapsed >= MISSING_EXECUTION_TIMEOUT_SECONDS:
                        logger.error(
                            "Dish missing workflow execution id past timeout",
                            extra={
                                "req_id": req_id,
                                "dish_id": dish.get("id"),
                                "elapsed_sec": int(elapsed),
                                "timeout_sec": MISSING_EXECUTION_TIMEOUT_SECONDS,
                            },
                        )
                        update_dish(
                            dish,
                            req_id,
                            processing_status="failed",
                            execution_status="abandoned",
                            error_msg="Missing workflow execution id",
                            final_status=True,
                        )
                continue

            st2_start_time = time.time()
            st2_resp = request_with_retry_sync(
                "GET",
                f"{API_BASE_URL}/cook/executions/{execution_id}",
                headers=get_service_headers(req_id),
                timeout=10,
                retries=POLLER_RETRIES,
            )
            st2_latency_ms = int((time.time() - st2_start_time) * 1000)

            if st2_resp.status_code == 200:
                st2_data = st2_resp.json()
                st2_status = str(st2_data.get("status") or "")
                st2_action_results = st2_data.get("result", {})
                dish_result = st2_action_results
                tasks_result = None
                if isinstance(st2_action_results, dict) and "tasks" in st2_action_results:
                    tasks_result = st2_action_results["tasks"]
                else:
                    # Fetch tasks explicitly if not included in execution result
                    try:
                        tasks_resp = request_with_retry_sync(
                            "GET",
                            f"{API_BASE_URL}/cook/executions/{execution_id}/tasks",
                            headers=get_service_headers(req_id),
                            timeout=10,
                            retries=POLLER_RETRIES,
                        )
                        if tasks_resp.status_code == 200:
                            tasks_result = tasks_resp.json()
                    except Exception:
                        tasks_result = None

                # If tasks lack timestamps, prefer child execution list for richer details
                def _tasks_missing_timestamps(tasks: list[dict[str, Any]]) -> bool:
                    if not tasks:
                        return True
                    for task in tasks:
                        if task.get("start_timestamp") or task.get("end_timestamp"):
                            return False
                    return True

                def _sort_tasks_by_execution(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
                    def _key(item: Any) -> tuple[str, str]:
                        start_ts = item.get("start_timestamp") or item.get("end_timestamp") or ""
                        end_ts = item.get("end_timestamp") or ""
                        return (start_ts, end_ts)

                    return sorted(tasks, key=_key)

                tasks_result = _normalize_tasks(tasks_result)

                if _tasks_missing_timestamps(tasks_result):
                    try:
                        children_resp = request_with_retry_sync(
                            "GET",
                            f"{API_BASE_URL}/cook/executions",
                            params={"parent": execution_id, "limit": 1000},
                            headers=get_service_headers(req_id),
                            timeout=10,
                            retries=POLLER_RETRIES,
                        )
                        if children_resp.status_code == 200:
                            children = children_resp.json()
                            tasks_result = _sort_tasks_by_execution(
                                [
                                    {
                                        "id": child.get("id"),
                                        "task_key": child.get("task_key")
                                        or child.get("context", {})
                                        .get("orquesta", {})
                                        .get("task_id"),
                                        "status": child.get("status"),
                                        "result": child.get("result"),
                                        "start_timestamp": child.get("start_timestamp"),
                                        "end_timestamp": child.get("end_timestamp"),
                                    }
                                    for child in children
                                    if isinstance(child, dict)
                                ]
                            )
                    except Exception:
                        pass

                if not tasks_result:
                    # Fallback: fetch child executions by parent id and store results
                    try:
                        children_resp = request_with_retry_sync(
                            "GET",
                            f"{API_BASE_URL}/cook/executions",
                            params={"parent": execution_id, "limit": 1000},
                            headers=get_service_headers(req_id),
                            timeout=10,
                            retries=POLLER_RETRIES,
                        )
                        if children_resp.status_code == 200:
                            children = children_resp.json()
                            tasks_result = _sort_tasks_by_execution(
                                [
                                    {
                                        "id": child.get("id"),
                                        "task_key": child.get("task_key")
                                        or child.get("context", {})
                                        .get("orquesta", {})
                                        .get("task_id"),
                                        "status": child.get("status"),
                                        "result": child.get("result"),
                                        "start_timestamp": child.get("start_timestamp"),
                                        "end_timestamp": child.get("end_timestamp"),
                                    }
                                    for child in children
                                    if isinstance(child, dict)
                                ]
                            )
                    except Exception:
                        tasks_result = []

                tasks_result = _sort_tasks_by_execution(tasks_result)

                dish_started_at = None
                if tasks_result:
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
                            ing_resp = request_with_retry_sync(
                                "GET",
                                f"{API_BASE_URL}/dishes/{dish.get('id')}/ingredients",
                                headers=get_service_headers(req_id),
                                timeout=10,
                                retries=POLLER_RETRIES,
                            )
                            if ing_resp.status_code == 200:
                                for ing in ing_resp.json():
                                    key = (
                                        ing.get("task_key") or "",
                                        ing.get("execution_ref"),
                                    )
                                    existing_status[key] = ing.get("execution_status")
                        except Exception:
                            existing_status = {}

                        for task in tasks_result:
                            if not isinstance(task, dict):
                                continue
                            task_status = task.get("status")
                            cache_key = (task.get("task_key") or "", task.get("id"))
                            prev_status = existing_status.get(cache_key)
                            if prev_status != task_status:
                                logger.debug(
                                    "Task status changed",
                                    extra={
                                        "req_id": req_id,
                                        "dish_id": dish.get("id"),
                                        "task_key": task.get("task_key"),
                                        "status": task_status,
                                    },
                                )

                            items.append(
                                {
                                    "execution_ref": task.get("id"),
                                    "task_key": task.get("task_key"),
                                    "execution_status": task_status,
                                    "started_at": task.get("start_timestamp")
                                    or dish.get("created_at"),
                                    "completed_at": task.get("end_timestamp"),
                                    "result": task.get("result"),
                                }
                            )

                        if items:
                            bulk_resp = request_with_retry_sync(
                                "POST",
                                f"{API_BASE_URL}/dishes/{dish.get('id')}/ingredients/bulk",
                                json={"items": items},
                                headers=get_service_headers(req_id),
                                timeout=10,
                                retries=POLLER_RETRIES,
                            )
                            if bulk_resp.status_code >= 400:
                                logger.warning(
                                    "Failed to persist dish ingredient execution updates",
                                    extra={
                                        "req_id": req_id,
                                        "dish_id": dish.get("id"),
                                        "status_code": bulk_resp.status_code,
                                        "response": bulk_resp.text,
                                    },
                                )
                    except Exception:
                        pass

                if st2_status in ST2_TERMINAL_STATUSES:
                    err = None
                    processing_status = "complete"
                    if st2_status in ST2_FAILURE_STATUSES:
                        processing_status = "failed"
                        err = st2_action_results.get("error") or "StackStorm execution failed"
                        retried, retry_error = _maybe_retry_missing_workflow_execution(
                            dish, req_id, err
                        )
                        if retried:
                            continue
                        if retry_error:
                            err = f"{err}; workflow file retry failed: {retry_error}"
                        _mark_pending_ingredients_failed(dish["id"], req_id, str(err))
                    elif st2_status == "succeeded":
                        try:
                            refreshed_ingredients = _fetch_dish_ingredients(int(dish["id"]), req_id)
                        except Exception as exc:  # noqa: BLE001
                            processing_status = "failed"
                            err = f"Failed to fetch next execution segment: {exc}"
                        else:
                            if (
                                next_pending_execution_segment(dish, refreshed_ingredients)
                                is not None
                            ):
                                if _requeue_dish_for_next_segment(
                                    dish,
                                    req_id,
                                    result=dish_result,
                                    started_at=dish_started_at or dish.get("started_at"),
                                ):
                                    logger.info(
                                        "Dish requeued for next execution segment",
                                        extra={
                                            "req_id": req_id,
                                            "dish_id": dish["id"],
                                            "execution_id": execution_id,
                                        },
                                    )
                                    continue
                                processing_status = "failed"
                                err = "Failed to requeue dish for next execution segment"

                    update_dish(
                        dish,
                        req_id,
                        processing_status=processing_status,
                        execution_status=st2_status,
                        error_msg=err,
                        final_status=True,
                        result=dish_result,
                        started_at=dish_started_at or dish.get("started_at"),
                    )
                    logger.info(
                        "Dish finalized with ST2 status",
                        extra={
                            **extra,
                            "dish_id": dish["id"],
                            "execution_id": execution_id,
                            "st2_status": st2_status,
                            "method": "GET",
                            "status_code": st2_resp.status_code,
                            "latency_ms": st2_latency_ms,
                        },
                    )
                else:
                    update_dish(
                        dish,
                        req_id,
                        processing_status="processing",
                        execution_status=st2_status,
                        final_status=False,
                        result=dish_result,
                        started_at=dish_started_at or dish.get("started_at"),
                    )
                    logger.debug(
                        "Dish execution still running; returning to processing",
                        extra={
                            **extra,
                            "dish_id": dish["id"],
                            "execution_id": execution_id,
                            "st2_status": st2_status,
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
                    "Dish execution not found in ST2",
                    extra={**extra, "dish_id": dish["id"], "execution_id": execution_id},
                )
                update_dish(
                    dish,
                    req_id,
                    processing_status="failed",
                    execution_status="abandoned",
                    error_msg="ST2 execution not found",
                    final_status=True,
                )
            else:
                logger.error(
                    "Dish execution returned unexpected status from ST2",
                    extra={
                        **extra,
                        "dish_id": dish["id"],
                        "execution_id": execution_id,
                        "method": "GET",
                        "status_code": st2_resp.status_code,
                        "latency_ms": st2_latency_ms,
                    },
                )

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        if API_UNAVAILABLE_SINCE is None:
            API_UNAVAILABLE_SINCE = time.time()
            logger.error(
                "Timer lost API connectivity",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "latency_ms": latency_ms,
                    "error": str(e),
                },
            )
        else:
            logger.debug(
                "Timer waiting for API recovery",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "latency_ms": latency_ms,
                    "error": str(e),
                },
            )


def run_suppression_lifecycle() -> None:
    """Run suppression summary lifecycle endpoint on a slower cadence."""
    global LAST_SUPPRESSION_LIFECYCLE_RUN
    now = time.time()
    if now - LAST_SUPPRESSION_LIFECYCLE_RUN < SUPPRESSION_LIFECYCLE_INTERVAL:
        return
    LAST_SUPPRESSION_LIFECYCLE_RUN = now
    try:
        resp = request_with_retry_sync(
            "POST",
            f"{API_BASE_URL}/suppressions/run-lifecycle",
            headers=get_service_headers(SYSTEM_REQ_ID),
            timeout=10,
            retries=POLLER_RETRIES,
        )
        if resp.status_code != 200:
            logger.warning(
                "Suppression lifecycle run returned non-200",
                extra={"req_id": SYSTEM_REQ_ID, "status_code": resp.status_code},
            )
            return
        payload = resp.json()
        logger.debug(
            "Suppression lifecycle completed",
            extra={"req_id": SYSTEM_REQ_ID, "finalized": payload.get("finalized", 0)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Suppression lifecycle run failed",
            extra={"req_id": SYSTEM_REQ_ID, "error": str(exc)},
        )


if __name__ == "__main__":
    wait_for_api(API_BASE_URL, SYSTEM_REQ_ID, logger)
    logger.info(
        "Timer started",
        extra={
            "req_id": SYSTEM_REQ_ID,
            "interval_sec": TIMER_INTERVAL,
            "sla_buffer_percent": int(SLA_BUFFER * 100),
            "poll_limit": POLL_LIMIT,
        },
    )
    while True:
        monitor_dishes()
        run_suppression_lifecycle()
        time.sleep(TIMER_INTERVAL)

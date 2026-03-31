#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Chef: Polls for pending dishes and dispatches phase-scoped execution."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from api.core.http_client import request_with_retry_sync

from api.core.config import get_settings
from api.core.logging import get_logger, setup_logging
from kitchen.execution_segments import (
    PENDING_EXECUTION_STATUSES,
    next_pending_execution_segment,
)
from kitchen.service_helpers import get_service_headers, wait_for_api

setup_logging()
logger = get_logger(__name__)

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://poundcake:8080").rstrip("/")
API_BASE_URL = f"{POUNDCAKE_API_URL}/api/v1"
POLL_INTERVAL = int(os.getenv("CHEF_POLL_INTERVAL", "5"))

SYSTEM_REQ_ID = "SYSTEM-CHEF"
POLLER_RETRIES = get_settings().poller_http_retries
CHEF_PATCH_RETRIES = get_settings().chef_patch_retries
CHEF_PATCH_RETRY_BACKOFF_SECONDS = get_settings().chef_patch_retry_backoff_seconds
CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES = max(0, get_settings().chef_execute_missing_workflow_retries)
CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS = max(
    0.1, get_settings().chef_execute_missing_workflow_retry_backoff_seconds
)
MISSING_WORKFLOW_PATH_FRAGMENT = "/opt/stackstorm/packs/poundcake/actions/workflows/"
PENDING_STATUSES = PENDING_EXECUTION_STATUSES


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _is_missing_workflow_file_response(response_text: str | None) -> bool:
    if not isinstance(response_text, str):
        return False
    return (
        "No such file or directory" in response_text
        and MISSING_WORKFLOW_PATH_FRAGMENT in response_text
    )


def _filter_stackstorm_recipe(
    recipe: dict[str, Any], recipe_ingredient_ids: set[int]
) -> dict[str, Any]:
    recipe_ingredients = recipe.get("recipe_ingredients")
    if not isinstance(recipe_ingredients, list):
        return recipe

    filtered_steps: list[dict[str, Any]] = []
    for item in recipe_ingredients:
        if not isinstance(item, dict):
            continue
        ingredient = item.get("ingredient")
        if not isinstance(ingredient, dict):
            continue
        if (ingredient.get("execution_engine") or "").strip().lower() != "stackstorm":
            continue

        ri_id = item.get("id")
        if isinstance(ri_id, int) and ri_id in recipe_ingredient_ids:
            filtered_steps.append(item)

    filtered = dict(recipe)
    filtered["recipe_ingredients"] = filtered_steps
    return filtered


def _fetch_dish_ingredients(dish_id: int, req_id: str) -> list[dict[str, Any]]:
    response = request_with_retry_sync(
        "GET",
        f"{API_BASE_URL}/dishes/{dish_id}/ingredients",
        headers=get_service_headers(req_id),
        timeout=10,
        retries=POLLER_RETRIES,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch dish ingredients: {response.text}")
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _upsert_dish_ingredient(dish_id: int, req_id: str, item: dict[str, Any]) -> None:
    request_with_retry_sync(
        "POST",
        f"{API_BASE_URL}/dishes/{dish_id}/ingredients/bulk",
        json={"items": [item]},
        headers=get_service_headers(req_id),
        timeout=10,
        retries=POLLER_RETRIES,
    )


def _execute_bakery_steps(
    *,
    dish: dict[str, Any],
    req_id: str,
    ingredients: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    dish_id = _coerce_int(dish.get("id"))
    if dish_id is None:
        raise ValueError("Dish id is required")
    order_id = dish.get("order_id")
    for item in ingredients:
        if (item.get("execution_engine") or "").strip().lower() != "bakery":
            continue
        if item.get("execution_status") not in PENDING_STATUSES:
            continue

        recipe_ingredient_id = _coerce_int(item.get("recipe_ingredient_id"))
        now = datetime.now(timezone.utc).isoformat()
        _upsert_dish_ingredient(
            dish_id,
            req_id,
            {
                "recipe_ingredient_id": recipe_ingredient_id,
                "task_key": item.get("task_key"),
                "execution_status": "running",
                "started_at": now,
                "execution_engine": "bakery",
                "execution_target": item.get("execution_target"),
                "destination_target": item.get("destination_target"),
            },
        )

        exec_resp = request_with_retry_sync(
            "POST",
            f"{API_BASE_URL}/cook/execute",
            json={
                "execution_engine": "bakery",
                "execution_target": item.get("execution_target"),
                "execution_payload": item.get("execution_payload") or {},
                "execution_parameters": item.get("execution_parameters") or {},
                "retry_count": int(item.get("retry_count") or 0),
                "retry_delay": int(item.get("retry_delay") or 0),
                "timeout_duration_sec": int(item.get("timeout_duration_sec") or 300),
                "context": {
                    "order_id": order_id,
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
        result_payload: dict[str, Any] | None = None
        if exec_resp.status_code in (200, 201):
            body = exec_resp.json()
            status = str(body.get("status") or "")
            execution_ref = body.get("execution_ref")
            result_payload = (
                body.get("raw") if isinstance(body.get("raw"), dict) else body.get("result")
            )
            success = status == "succeeded"
            if not success:
                error_message = str(body.get("error_message") or "Bakery execution failed")
        else:
            error_message = str(exec_resp.text)

        _upsert_dish_ingredient(
            dish_id,
            req_id,
            {
                "recipe_ingredient_id": recipe_ingredient_id,
                "task_key": item.get("task_key"),
                "execution_status": "succeeded" if success else "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "execution_ref": execution_ref,
                "result": result_payload,
                "error_message": error_message,
                "execution_engine": "bakery",
                "execution_target": item.get("execution_target"),
                "destination_target": item.get("destination_target"),
            },
        )

        on_failure = str(item.get("on_failure") or "stop").lower()
        if not success and on_failure != "continue":
            return False, error_message

    return True, None


def _finalize_dish(dish_id: int, req_id: str, *, success: bool, error: str | None = None) -> None:
    request_with_retry_sync(
        "PATCH",
        f"{API_BASE_URL}/dishes/{dish_id}",
        json={
            "processing_status": "complete" if success else "failed",
            "execution_status": "succeeded" if success else "failed",
            "error_message": None if success else (error or "Dish execution failed"),
        },
        headers=get_service_headers(req_id),
        timeout=10,
        retries=CHEF_PATCH_RETRIES,
        retry_backoff_seconds=CHEF_PATCH_RETRY_BACKOFF_SECONDS,
    )


def _start_stackstorm_workflow(
    *,
    dish_id: int,
    req_id: str,
    recipe: dict[str, Any],
    stackstorm_ingredient_rows: list[dict[str, Any]],
) -> None:
    recipe_ingredient_ids = {
        int(item["recipe_ingredient_id"])
        for item in stackstorm_ingredient_rows
        if isinstance(item.get("recipe_ingredient_id"), int)
    }
    filtered_recipe = _filter_stackstorm_recipe(recipe, recipe_ingredient_ids)

    reg_resp = request_with_retry_sync(
        "POST",
        f"{API_BASE_URL}/cook/workflows/register",
        json={
            "name": filtered_recipe.get("name"),
            "description": filtered_recipe.get("description"),
            "execution_parameters": filtered_recipe.get("execution_parameters"),
        },
        headers=get_service_headers(req_id),
        timeout=30,
        retries=POLLER_RETRIES,
    )
    if reg_resp.status_code not in (200, 201):
        raise RuntimeError(reg_resp.text)
    workflow_id = reg_resp.json().get("workflow_id")

    st2_exec_id = None
    max_attempts = 1 + CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES
    for attempt in range(1, max_attempts + 1):
        exec_resp = request_with_retry_sync(
            "POST",
            f"{API_BASE_URL}/cook/execute",
            json={
                "execution_engine": "stackstorm",
                "execution_target": workflow_id,
                "execution_parameters": {},
            },
            headers=get_service_headers(req_id),
            timeout=30,
            retries=POLLER_RETRIES,
        )
        if exec_resp.status_code in (200, 201):
            body = exec_resp.json()
            if body.get("status") in {"queued", "running", "succeeded"}:
                st2_exec_id = body.get("execution_ref")
                break
            error_text = str(body.get("error_message") or exec_resp.text)
            if attempt < max_attempts and _is_missing_workflow_file_response(error_text):
                time.sleep(CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS)
                continue
            raise RuntimeError(error_text)

        if attempt < max_attempts and _is_missing_workflow_file_response(exec_resp.text):
            time.sleep(CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS)
            continue

        raise RuntimeError(exec_resp.text)

    if not st2_exec_id:
        raise RuntimeError("StackStorm execution did not return an execution id after retries")

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
        raise RuntimeError(f"Failed to persist workflow execution id: {patch_resp.text}")


def run_chef() -> None:
    """Main chef loop - polls for new dishes and dispatches stage execution."""
    wait_for_api(API_BASE_URL, SYSTEM_REQ_ID, logger)

    logger.info(
        "Chef started",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_BASE_URL, "poll_interval": POLL_INTERVAL},
    )
    api_unavailable_since: float | None = None

    while True:
        try:
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
            dish_id = int(dish.get("id"))
            while True:
                ingredients = _fetch_dish_ingredients(dish_id, req_id)
                next_segment = next_pending_execution_segment(dish, ingredients)
                if next_segment is None:
                    _finalize_dish(dish_id, req_id, success=True)
                    break

                segment_engine, segment_items = next_segment
                if segment_engine == "bakery":
                    ok, err = _execute_bakery_steps(
                        dish=dish,
                        req_id=req_id,
                        ingredients=segment_items,
                    )
                    if not ok:
                        _finalize_dish(dish_id, req_id, success=False, error=err)
                        break
                    continue

                if segment_engine == "stackstorm":
                    try:
                        recipe = dish.get("recipe") if isinstance(dish.get("recipe"), dict) else {}
                        _start_stackstorm_workflow(
                            dish_id=dish_id,
                            req_id=req_id,
                            recipe=recipe,
                            stackstorm_ingredient_rows=segment_items,
                        )
                        logger.info(
                            "StackStorm workflow execution started",
                            extra={
                                "req_id": req_id,
                                "dish_id": dish_id,
                                "run_phase": dish.get("run_phase"),
                                "segment_size": len(segment_items),
                            },
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Workflow execution failed",
                            extra={"req_id": req_id, "dish_id": dish_id, "error": str(exc)},
                        )
                        _finalize_dish(dish_id, req_id, success=False, error=str(exc))
                    break

                _finalize_dish(
                    dish_id,
                    req_id,
                    success=False,
                    error=f"Unsupported segment engine: {segment_engine}",
                )
                break

        except Exception as e:  # noqa: BLE001
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

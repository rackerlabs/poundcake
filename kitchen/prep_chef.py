#!/usr/bin/env python3
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prep Chef: Polls for dispatchable orders and triggers unified order dispatch."""

import os
import time
from datetime import datetime
from typing import Any

from api.core.logging import setup_logging, get_logger
from api.core.config import get_settings
import kitchen.service_helpers as service_helpers

# Initialize logging with standardized configuration
setup_logging()
logger = get_logger(__name__)

POUNDCAKE_API_URL = os.getenv("POUNDCAKE_API_URL", "http://poundcake:8080").rstrip("/")
API_URL = f"{POUNDCAKE_API_URL}/api/v1"
PREP_INTERVAL = int(os.getenv("PREP_INTERVAL", "5"))

# System request ID for prep chef operations
SYSTEM_REQ_ID = "SYSTEM-PREP-CHEF"
POLLER_RETRIES = get_settings().poller_http_retries
POLL_LIMIT = int(os.getenv("PREP_CHEF_LIMIT", "10"))
DISPATCHABLE_ORDER_QUERIES = (
    {"processing_status": "new"},
    {"processing_status": "resolving", "alert_status": "resolved"},
)


def _parse_timestamp(ts: Any) -> float:
    """Extract unix epoch timestamp from string or numeric created_at field."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str) and ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            pass
    return time.time()


def _is_order_ready_for_dispatch(order: dict[str, Any]) -> tuple[bool, str]:
    """
    Evaluates whether an order with correlation/delay settings is ready for cooking.
    Returns (is_ready, reason_string).
    """
    context = order.get("context") if isinstance(order.get("context"), dict) else {}
    labels = order.get("labels") or context.get("labels") or {}
    annotations = order.get("annotations") or context.get("annotations") or {}
    metadata = order.get("metadata") or context.get("metadata") or {}

    is_root_cause = str(labels.get("root_cause", "")).lower() == "true"
    dispatch_min_wait_sec = int(labels.get("dispatch_min_wait_sec") or 0)
    dispatch_delay_sec = int(labels.get("dispatch_delay_sec") or 0)

    # Standalone orders or orders without dispatch delay are ready immediately
    if not is_root_cause and dispatch_delay_sec <= 0 and dispatch_min_wait_sec <= 0:
        return True, "standard_order"

    # Extract child counts and timing
    expected_children = int(
        annotations.get("expected_child_count") or order.get("expected_child_count") or 0
    )
    children = metadata.get("children") or order.get("children") or []
    child_count = int(order.get("child_count") or len(children))

    created_at_epoch = _parse_timestamp(
        order.get("created_at") or order.get("timestamp") or metadata.get("created_at")
    )
    elapsed_sec = max(0.0, time.time() - created_at_epoch)

    min_wait_passed = elapsed_sec >= dispatch_min_wait_sec
    all_children_arrived = (expected_children > 0 and child_count >= expected_children) or (
        expected_children == 0 and min_wait_passed
    )
    max_delay_reached = dispatch_delay_sec > 0 and elapsed_sec >= dispatch_delay_sec

    if min_wait_passed and all_children_arrived:
        return (
            True,
            f"all_children_arrived({child_count}/{expected_children}_in_{int(elapsed_sec)}s)",
        )
    if max_delay_reached:
        return (
            True,
            f"max_delay_reached({int(elapsed_sec)}s>={dispatch_delay_sec}s_children={child_count}/{expected_children})",
        )

    return (
        False,
        f"buffering(elapsed={int(elapsed_sec)}s/{dispatch_min_wait_sec}s_children={child_count}/{expected_children})",
    )


def _fetch_dispatchable_orders(loop_limit: int) -> list[dict]:
    orders: list[dict] = []
    for query in DISPATCHABLE_ORDER_QUERIES:
        start_time = time.time()
        params = {**query, "limit": loop_limit}
        resp = service_helpers.request_control_plane_sync(
            "GET",
            f"{API_URL}/orders",
            params=params,
            req_id=SYSTEM_REQ_ID,
            timeout=10,
            retries=POLLER_RETRIES,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        if resp.status_code != 200:
            logger.error(
                "Failed to fetch orders",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "status": query["processing_status"],
                    "alert_status": query.get("alert_status"),
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                },
            )
            continue

        fetched = resp.json()
        if not isinstance(fetched, list):
            continue
        orders.extend(item for item in fetched if isinstance(item, dict))
    return orders


def _dispatch_orders(orders: list[dict]) -> None:
    seen_order_ids: set[object] = set()
    for order in orders:
        order_id = order.get("id")
        if order_id in seen_order_ids:
            continue
        seen_order_ids.add(order_id)
        req_id = order.get("req_id", "UNKNOWN")
        processing_status = order.get("processing_status")

        # Check if root/delayed order is ready to be cooked
        is_ready, reason = _is_order_ready_for_dispatch(order)
        if not is_ready:
            logger.info(
                "Order buffering - delaying dispatch",
                extra={
                    "req_id": req_id,
                    "order_id": order_id,
                    "reason": reason,
                    "processing_status": processing_status,
                },
            )
            continue

        logger.info(
            "Preparing order for cooking",
            extra={"req_id": req_id, "order_id": order_id, "dispatch_reason": reason},
        )

        start_time = time.time()
        cook_resp = service_helpers.request_control_plane_sync(
            "POST",
            f"{API_URL}/cook/orders/{order_id}",
            req_id=req_id,
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
                    "processing_status": processing_status,
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
                    "processing_status": processing_status,
                    "method": "POST",
                    "status_code": cook_resp.status_code,
                    "latency_ms": latency_ms,
                    "response": cook_resp.text,
                },
            )


def _run_once(loop_limit: int) -> None:
    _dispatch_orders(_fetch_dispatchable_orders(loop_limit))


def prep_loop() -> None:
    """Main prep chef loop - polls for new orders and triggers cooking."""
    service_helpers.wait_for_api(API_URL, SYSTEM_REQ_ID, logger, delay_sec=PREP_INTERVAL)
    logger.info(
        "Starting prep chef",
        extra={"req_id": SYSTEM_REQ_ID, "api_url": API_URL, "poll_interval": PREP_INTERVAL},
    )
    api_unavailable_since: float | None = None

    while True:
        runtime_config = service_helpers.get_worker_runtime_config(
            api_base_url=API_URL,
            service_type="prep-chef",
            req_id=SYSTEM_REQ_ID,
            default_interval=PREP_INTERVAL,
            default_query_limit=POLL_LIMIT,
            logger=logger,
        )
        loop_interval = int(runtime_config["run_interval_seconds"])
        loop_limit = int(runtime_config["query_limit"])
        if not runtime_config["enabled"]:
            logger.info(
                "Prep chef paused by internal plugin configuration",
                extra={"req_id": SYSTEM_REQ_ID, "poll_interval": loop_interval},
            )
            time.sleep(loop_interval)
            continue
        try:
            _run_once(loop_limit)
            if api_unavailable_since is not None:
                downtime_sec = int(time.time() - api_unavailable_since)
                logger.info(
                    "Prep chef API connectivity restored",
                    extra={"req_id": SYSTEM_REQ_ID, "downtime_sec": downtime_sec},
                )
                api_unavailable_since = None

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

        time.sleep(loop_interval)


if __name__ == "__main__":
    prep_loop()

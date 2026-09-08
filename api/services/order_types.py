"""Helpers for the stable order_type contract."""

from __future__ import annotations

from typing import Any

from api.types import (
    ALL_ORDER_TYPES,
    MANUAL_ORDER_TYPE,
    OPERATOR_ORDER_TYPES,
    SCHEDULED_TASK_ORDER_TYPE,
    SYSTEM_ORDER_TYPES,
    WEBHOOK_ALERT_ORDER_TYPE,
    OrderScope,
    OrderType,
)


def normalize_order_type(value: Any) -> OrderType | None:
    """Return a known order_type value or None."""
    normalized = str(value or "").strip().lower()
    if normalized in ALL_ORDER_TYPES:
        return normalized  # type: ignore[return-value]
    return None


def require_order_type(raw_data: Any) -> OrderType:
    """Return the explicit order_type stored on the order payload."""
    raw = raw_data if isinstance(raw_data, dict) else {}
    explicit = normalize_order_type(raw.get("order_type"))
    if explicit is None:
        raise ValueError("order_type must be present in raw_data")
    return explicit


def order_is_subject_to_alert_suppressions(raw_data: Any) -> bool:
    """Return whether alert suppressions may short-circuit this order.

    Catch-all silences match any ``alertname``. Operator-action and scheduled
    orders reuse that label for the recipe/task name, so applying suppressions
    to them would cancel their own expire/export work.
    """
    raw = raw_data if isinstance(raw_data, dict) else {}
    if raw.get("operator_action") is True:
        return False
    order_type = normalize_order_type(raw.get("order_type"))
    if order_type in {MANUAL_ORDER_TYPE, SCHEDULED_TASK_ORDER_TYPE}:
        return False
    return order_type in {WEBHOOK_ALERT_ORDER_TYPE, None}


def order_scope_types(scope: OrderScope | None) -> frozenset[OrderType]:
    """Return the allowed order types for a reporting scope."""
    if scope == "operator":
        return OPERATOR_ORDER_TYPES
    if scope == "system":
        return SYSTEM_ORDER_TYPES
    return ALL_ORDER_TYPES


def order_matches_filters(
    *,
    raw_data: Any,
    order_scope: OrderScope | None = None,
    order_type: OrderType | None = None,
) -> bool:
    """Return whether an order belongs in the requested reporting view."""
    explicit = require_order_type(raw_data)
    if order_type and explicit != order_type:
        return False
    return explicit in order_scope_types(order_scope)


def ensure_raw_data_order_type(raw_data: Any, default: OrderType) -> dict[str, Any]:
    """Copy raw_data and ensure it has a valid order_type."""
    payload = dict(raw_data) if isinstance(raw_data, dict) else {}
    current = payload.get("order_type")
    if current is None or current == "":
        payload["order_type"] = default
        return payload
    normalized = normalize_order_type(current)
    if normalized is None:
        raise ValueError("order_type must be one of: " + ", ".join(sorted(ALL_ORDER_TYPES)))
    payload["order_type"] = normalized
    return payload

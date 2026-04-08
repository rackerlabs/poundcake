"""Active incident reconciliation across Prometheus alert state and Bakery ticket state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.core.statuses import can_transition_to_resolving
from api.models.models import DishIngredient, Order, OrderCommunication
from api.services.bakery_client import (
    notify_communication,
    open_communication,
    poll_operation,
    update_communication,
)
from api.services.communications import (
    is_ticket_capable_destination,
    normalize_destination_target,
    normalize_destination_type,
)
from api.services.communications_policy import POLICY_METADATA_KEY
from api.services.order_communications import (
    is_remote_state_terminal,
    is_ticket_communication,
    load_order_with_communications,
    refresh_remote_state,
)
from api.services.prometheus_service import get_prometheus_client

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sync_legacy_order_fields(order: Order) -> None:
    ticket_routes = [
        item
        for item in (order.communications or [])
        if item.bakery_ticket_id and is_ticket_capable_destination(item.execution_target)
    ]
    if len(ticket_routes) == 1:
        item = ticket_routes[0]
        order.bakery_ticket_id = item.bakery_ticket_id
        order.bakery_operation_id = item.bakery_operation_id
        order.bakery_ticket_state = item.remote_state
        order.bakery_last_error = item.last_error
        order.bakery_permanent_failure = (item.lifecycle_state or "") == "dead_letter"
        order.bakery_comms_id = item.bakery_ticket_id
        return
    order.bakery_ticket_id = None
    order.bakery_operation_id = None
    order.bakery_ticket_state = None
    order.bakery_last_error = None
    order.bakery_permanent_failure = False
    order.bakery_comms_id = None


def _matching_labels(order: Order) -> dict[str, str]:
    labels = dict(order.labels or {})
    keys = ("alertname", "group_name", "instance", "job", "namespace", "cluster", "service")
    result: dict[str, str] = {}
    for key in keys:
        value = labels.get(key)
        if value not in (None, ""):
            result[key] = str(value)
    return result


def _alert_matches_order(order: Order, alert: dict[str, Any]) -> bool:
    if not isinstance(alert, dict):
        return False
    labels = alert.get("labels")
    if not isinstance(labels, dict):
        return False

    alert_fingerprint = str(alert.get("fingerprint") or "").strip()
    if alert_fingerprint and alert_fingerprint == str(order.fingerprint or "").strip():
        return True

    expected = _matching_labels(order)
    if not expected:
        return False
    for key, value in expected.items():
        current = labels.get(key)
        if current in (None, ""):
            return False
        if str(current) != value:
            return False
    return True


def _alert_is_firing(order: Order, alerts: list[dict[str, Any]]) -> bool:
    for alert in alerts:
        state = str(alert.get("state") or "").strip().lower()
        if state and state != "firing":
            continue
        if _alert_matches_order(order, alert):
            return True
    return False


def _route_metadata(order: Order, communication: OrderCommunication) -> dict[str, Any]:
    metadata = dict(communication.reconcile_metadata or {})
    if metadata.get("provider_config") and metadata.get("route_label"):
        return metadata
    if metadata.get("route_label") and all(
        str(metadata.get(key) or "").strip() for key in ("scope", "owner_key", "route_id")
    ):
        return metadata

    def _matching_item(item: DishIngredient) -> bool:
        return (
            str(item.execution_engine or "").strip().lower() == "bakery"
            and normalize_destination_type(item.execution_target) == communication.execution_target
            and normalize_destination_target(item.destination_target)
            == communication.destination_target
        )

    dishes = sorted(
        list(order.dishes or []),
        key=lambda item: (item.created_at or _now(), item.id or 0),
        reverse=True,
    )
    for dish in dishes:
        items = sorted(
            list(dish.dish_ingredients or []),
            key=lambda item: (item.created_at or _now(), item.id or 0),
            reverse=True,
        )
        for item in items:
            if not _matching_item(item):
                continue
            payload = item.execution_payload if isinstance(item.execution_payload, dict) else {}
            context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            provider_config = context.get("provider_config")
            if isinstance(provider_config, dict) and provider_config:
                metadata.setdefault("provider_config", dict(provider_config))
            policy_metadata = context.get(POLICY_METADATA_KEY)
            if isinstance(policy_metadata, dict) and policy_metadata:
                for key in (
                    "scope",
                    "owner_key",
                    "route_id",
                    "label",
                    "execution_target",
                    "destination_target",
                ):
                    value = policy_metadata.get(key)
                    if isinstance(value, str) and value.strip():
                        metadata.setdefault(key, value.strip())
                policy_provider_config = policy_metadata.get("provider_config")
                if isinstance(policy_provider_config, dict) and policy_provider_config:
                    metadata.setdefault("provider_config", dict(policy_provider_config))
            route_label = context.get("route_label")
            if isinstance(route_label, str) and route_label.strip():
                metadata.setdefault("route_label", route_label.strip())
            if not metadata.get("route_label"):
                policy_label = metadata.get("label")
                if isinstance(policy_label, str) and policy_label.strip():
                    metadata.setdefault("route_label", policy_label.strip())
            if metadata.get("provider_config") and metadata.get("route_label"):
                communication.reconcile_metadata = metadata
                return metadata
    communication.reconcile_metadata = metadata
    return metadata


def _headline(order: Order) -> str:
    annotations = dict(order.annotations or {})
    return str(annotations.get("summary") or order.alert_group_name or "Alert").strip()


def _description(order: Order) -> str:
    annotations = dict(order.annotations or {})
    return str(
        annotations.get("description")
        or annotations.get("summary")
        or f"Alert {order.alert_group_name} is active."
    ).strip()


def _firing_ticket_note(order: Order, communication: OrderCommunication) -> str:
    route = _route_metadata(order, communication)
    route_label = str(route.get("route_label") or communication.execution_target).strip()
    return (
        f"Alert {order.alert_group_name} is still firing. PoundCake reopened or recreated the "
        f"{route_label} incident because it cannot be closed until the alert clears."
    )


def _clear_ticket_note(order: Order, communication: OrderCommunication) -> str:
    route = _route_metadata(order, communication)
    route_label = str(route.get("route_label") or communication.execution_target).strip()
    return (
        f"Alert {order.alert_group_name} is clear. PoundCake will keep monitoring {route_label} "
        "until the ticket is closed, then the PoundCake incident will close."
    )


def _reconcile_context(order: Order, communication: OrderCommunication) -> dict[str, Any]:
    route = _route_metadata(order, communication)
    context: dict[str, Any] = {
        "source": "poundcake_system",
        "provider_type": communication.execution_target,
        "execution_target": communication.execution_target,
        "destination_target": communication.destination_target,
        "route_label": str(route.get("route_label") or communication.execution_target).strip(),
        "labels": dict(order.labels or {}),
        "annotations": dict(order.annotations or {}),
    }
    provider_config = route.get("provider_config")
    if isinstance(provider_config, dict) and provider_config:
        context["provider_config"] = dict(provider_config)
    if all(str(route.get(key) or "").strip() for key in ("scope", "owner_key", "route_id")):
        context[POLICY_METADATA_KEY] = {
            "scope": str(route.get("scope") or "").strip(),
            "owner_key": str(route.get("owner_key") or "").strip(),
            "route_id": str(route.get("route_id") or "").strip(),
            "label": str(route.get("route_label") or route.get("label") or "").strip(),
            "execution_target": str(
                route.get("execution_target") or communication.execution_target
            ),
            "destination_target": str(
                route.get("destination_target") or communication.destination_target
            ),
            "provider_config": dict(provider_config or {}),
        }
    return context


def _open_payload(order: Order, communication: OrderCommunication) -> dict[str, Any]:
    context = _reconcile_context(order, communication)
    return {
        "title": _headline(order),
        "description": _description(order),
        "message": _firing_ticket_note(order, communication),
        "source": "poundcake_system",
        "context": context,
    }


def _reopen_payload(order: Order, communication: OrderCommunication) -> dict[str, Any]:
    execution_target = communication.execution_target
    target = normalize_destination_type(execution_target)
    if target == "rackspace_core":
        return {
            "state": "open",
            "context": {
                **_reconcile_context(order, communication),
                "attributes": {"status": "New"},
            },
        }
    return {"state": "open", "context": _reconcile_context(order, communication)}


def _has_open_ticket_routes(order: Order) -> bool:
    return any(
        is_ticket_communication(item) and not is_remote_state_terminal(item.remote_state)
        for item in (order.communications or [])
    )


async def _await_operation(operation_id: str) -> tuple[bool, str | None]:
    payload = await poll_operation(operation_id)
    status = str(payload.status or "").strip().lower()
    if status in {"succeeded", "success", "completed"}:
        return True, None
    return False, str(
        payload.last_error or f"Bakery operation ended in status={status or 'unknown'}"
    )


async def _reopen_or_recreate_ticket(
    *,
    order: Order,
    communication: OrderCommunication,
    req_id: str,
    actions: list[str],
) -> None:
    metadata = dict(communication.reconcile_metadata or {})
    old_ticket_id = str(communication.bakery_ticket_id or "").strip()
    if not old_ticket_id:
        return

    if communication.reopenable:
        if metadata.get("last_reopen_ticket_id") == old_ticket_id:
            communication.reconcile_metadata = metadata
            return
        accepted = await update_communication(
            req_id=req_id,
            communication_id=old_ticket_id,
            payload=_reopen_payload(order, communication),
        )
        success, error = await _await_operation(accepted.operation_id)
        communication.bakery_operation_id = accepted.operation_id
        communication.lifecycle_state = "succeeded" if success else "failed"
        communication.last_error = error
        if not success:
            communication.reconcile_metadata = metadata
            return
        communication.remote_state = "open"
        communication.writable = True
        communication.reopenable = False
        note = await notify_communication(
            req_id=req_id,
            communication_id=old_ticket_id,
            payload={
                "comment": _firing_ticket_note(order, communication),
                "context": _reconcile_context(order, communication),
            },
        )
        note_success, note_error = await _await_operation(note.operation_id)
        communication.bakery_operation_id = note.operation_id
        if not note_success:
            communication.lifecycle_state = "failed"
            communication.last_error = note_error
            communication.reconcile_metadata = metadata
            return
        await refresh_remote_state(communication)
        metadata["last_reopen_ticket_id"] = old_ticket_id
        metadata.pop("last_clear_note_ticket_id", None)
        communication.reconcile_metadata = metadata
        actions.append(
            f"reopened:{communication.execution_target}:{communication.destination_target}"
        )
        return

    if metadata.get("last_successor_from_ticket_id") == old_ticket_id:
        communication.reconcile_metadata = metadata
        return

    accepted = await open_communication(req_id=req_id, payload=_open_payload(order, communication))
    success, error = await _await_operation(accepted.operation_id)
    communication.bakery_operation_id = accepted.operation_id
    communication.lifecycle_state = "succeeded" if success else "failed"
    communication.last_error = error
    if not success:
        communication.reconcile_metadata = metadata
        return
    communication.bakery_ticket_id = accepted.communication_id
    communication.remote_state = "open"
    communication.writable = True
    communication.reopenable = False
    metadata["last_successor_from_ticket_id"] = old_ticket_id
    metadata.pop("last_clear_note_ticket_id", None)
    communication.reconcile_metadata = metadata
    await refresh_remote_state(communication)
    actions.append(
        f"recreated:{communication.execution_target}:{communication.destination_target}:{accepted.communication_id}"
    )


async def _notify_clear_ticket(
    *,
    order: Order,
    communication: OrderCommunication,
    req_id: str,
    actions: list[str],
) -> None:
    metadata = dict(communication.reconcile_metadata or {})
    ticket_id = str(communication.bakery_ticket_id or "").strip()
    if not ticket_id:
        return
    if metadata.get("last_clear_note_ticket_id") == ticket_id:
        communication.reconcile_metadata = metadata
        return
    accepted = await notify_communication(
        req_id=req_id,
        communication_id=ticket_id,
        payload={
            "comment": _clear_ticket_note(order, communication),
            "context": _reconcile_context(order, communication),
        },
    )
    success, error = await _await_operation(accepted.operation_id)
    communication.bakery_operation_id = accepted.operation_id
    communication.lifecycle_state = "succeeded" if success else "failed"
    communication.last_error = error
    if not success:
        communication.reconcile_metadata = metadata
        return
    metadata["last_clear_note_ticket_id"] = ticket_id
    communication.reconcile_metadata = metadata
    await refresh_remote_state(communication)
    actions.append(
        f"notified_clear:{communication.execution_target}:{communication.destination_target}"
    )


async def reconcile_order(
    db: AsyncSession,
    *,
    order_id: int,
    req_id: str,
) -> dict[str, Any]:
    order = await load_order_with_communications(db, order_id=order_id, for_update=True)
    if order is None:
        raise ValueError(f"Order {order_id} not found")

    result: dict[str, Any] = {
        "order_id": order.id,
        "processing_status": order.processing_status,
        "alert_status": order.alert_status,
        "actions": [],
    }

    if str(order.processing_status or "").strip().lower() in {"complete", "failed", "canceled"}:
        result["status"] = "skipped"
        return result

    alerts = await get_prometheus_client().get_alerts()
    if alerts is None:
        result["status"] = "deferred"
        result["reason"] = "prometheus_unavailable"
        return result

    alert_firing = _alert_is_firing(order, alerts)
    now = _now()
    result["observed_alert_status"] = "firing" if alert_firing else "resolved"

    if alert_firing:
        order.alert_status = "firing"
        order.ends_at = None
        order.is_active = True
        if str(order.processing_status or "").strip().lower() in {
            "resolving",
            "waiting_ticket_close",
        }:
            order.processing_status = "new"
            result["actions"].append("redispatch_firing")
    else:
        order.alert_status = "resolved"
        order.ends_at = order.ends_at or now
        order.is_active = True
        if can_transition_to_resolving(order.processing_status, "alert_resolved"):
            if str(order.processing_status or "").strip().lower() != "resolving":
                order.processing_status = "resolving"
                result["actions"].append("dispatch_resolving")

    ticket_routes = [
        communication
        for communication in (order.communications or [])
        if is_ticket_communication(communication)
    ]
    try:
        for communication in ticket_routes:
            remote_state, writable, reopenable = await refresh_remote_state(
                communication,
                raise_on_error=True,
            )
            communication.remote_state = remote_state
            communication.writable = writable
            communication.reopenable = reopenable
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Incident reconciliation deferred after Bakery sync failure",
            extra={"req_id": req_id, "order_id": order.id, "error": str(exc)},
        )
        order.updated_at = now
        _sync_legacy_order_fields(order)
        await db.flush()
        result["status"] = "deferred"
        result["reason"] = "bakery_sync_failed"
        return result

    for communication in ticket_routes:
        metadata = dict(communication.reconcile_metadata or {})
        if alert_firing and not is_remote_state_terminal(communication.remote_state):
            metadata.pop("last_reopen_ticket_id", None)
            metadata.pop("last_clear_note_ticket_id", None)
            communication.reconcile_metadata = metadata
            continue
        if not alert_firing and is_remote_state_terminal(communication.remote_state):
            metadata.pop("last_clear_note_ticket_id", None)
            communication.reconcile_metadata = metadata

    if alert_firing:
        for communication in ticket_routes:
            if is_remote_state_terminal(communication.remote_state):
                await _reopen_or_recreate_ticket(
                    order=order,
                    communication=communication,
                    req_id=req_id,
                    actions=result["actions"],
                )
    else:
        for communication in ticket_routes:
            if not is_remote_state_terminal(communication.remote_state):
                await _notify_clear_ticket(
                    order=order,
                    communication=communication,
                    req_id=req_id,
                    actions=result["actions"],
                )

    if (
        not alert_firing
        and str(order.processing_status or "").strip().lower() == "waiting_ticket_close"
    ):
        if not _has_open_ticket_routes(order):
            order.processing_status = "complete"
            order.is_active = False
            result["actions"].append("complete_incident")

    order.updated_at = now
    _sync_legacy_order_fields(order)
    await db.flush()

    result["status"] = "reconciled"
    result["processing_status"] = order.processing_status
    result["alert_status"] = order.alert_status
    result["has_open_ticket_routes"] = _has_open_ticket_routes(order)
    return result

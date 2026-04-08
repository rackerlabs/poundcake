"""Helpers for tracking and reusing order communications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.logging import get_logger
from api.models.models import Dish, DishIngredient, Order, OrderCommunication, RecipeIngredient
from api.services.communications_policy import POLICY_METADATA_KEY
from api.services.bakery_client import sync_communication
from api.services.communications import (
    is_ticket_capable_destination,
    normalize_destination_target,
    normalize_destination_type,
)

logger = get_logger(__name__)

TERMINAL_REMOTE_STATES = {
    "closed",
    "confirmed_solved",
    "terminal",
    "solved",
    "resolved",
    "done",
    "completed",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_remote_state(state: Any) -> str:
    return str(state or "").strip().lower().replace(" ", "_")


def is_remote_state_terminal(remote_state: str | None) -> bool:
    return normalize_remote_state(remote_state) in TERMINAL_REMOTE_STATES


def is_ticket_communication(communication: OrderCommunication) -> bool:
    return bool(communication.bakery_ticket_id) and is_ticket_capable_destination(
        communication.execution_target
    )


def determine_writeability(*, execution_target: str, remote_state: str | None) -> tuple[bool, bool]:
    normalized_target = normalize_destination_type(execution_target)
    normalized_state = normalize_remote_state(remote_state)
    if normalized_target == "rackspace_core" and normalized_state == "confirmed_solved":
        return True, True
    if normalized_state in TERMINAL_REMOTE_STATES:
        return False, False
    if not normalized_state:
        return True, False
    return True, False


def _remember_route_metadata(
    communication: OrderCommunication,
    *,
    execution_target: str,
    execution_payload: dict[str, Any] | None,
) -> None:
    payload = execution_payload if isinstance(execution_payload, dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    metadata = dict(communication.reconcile_metadata or {})
    metadata["execution_target"] = normalize_destination_type(execution_target)
    metadata["destination_target"] = normalize_destination_target(
        context.get("destination_target") or communication.destination_target
    )
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
                metadata[key] = value.strip()
        policy_provider_config = policy_metadata.get("provider_config")
        if isinstance(policy_provider_config, dict) and policy_provider_config:
            metadata["provider_config"] = dict(policy_provider_config)
    provider_config = context.get("provider_config")
    if isinstance(provider_config, dict) and provider_config:
        metadata["provider_config"] = dict(provider_config)
    route_label = context.get("route_label")
    if isinstance(route_label, str) and route_label.strip():
        metadata["route_label"] = route_label.strip()
    if not metadata.get("route_label"):
        policy_label = metadata.get("label")
        if isinstance(policy_label, str) and policy_label.strip():
            metadata["route_label"] = policy_label.strip()
    communication.reconcile_metadata = metadata


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


def build_route_key(*, execution_target: str, destination_target: str | None) -> tuple[str, str]:
    return normalize_destination_type(execution_target), normalize_destination_target(
        destination_target
    )


def find_communication_for_route(
    order: Order, *, execution_target: str, destination_target: str | None
) -> OrderCommunication | None:
    route_key = build_route_key(
        execution_target=execution_target,
        destination_target=destination_target,
    )
    for item in order.communications or []:
        if (
            build_route_key(
                execution_target=item.execution_target,
                destination_target=item.destination_target,
            )
            == route_key
        ):
            return item
    return None


async def load_order_with_communications(
    db: AsyncSession, *, order_id: int, for_update: bool = False
) -> Order | None:
    query = (
        select(Order)
        .options(
            selectinload(Order.communications),
            selectinload(Order.dishes)
            .selectinload(Dish.dish_ingredients)
            .selectinload(DishIngredient.recipe_ingredient)
            .selectinload(RecipeIngredient.ingredient),
        )
        .where(Order.id == order_id)
    )
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.unique().scalars().first()


async def ensure_order_communication(
    db: AsyncSession,
    *,
    order: Order,
    execution_target: str,
    destination_target: str | None,
) -> OrderCommunication:
    existing = find_communication_for_route(
        order,
        execution_target=execution_target,
        destination_target=destination_target,
    )
    if existing is not None:
        return existing
    communication = OrderCommunication(
        order_id=order.id,
        execution_target=normalize_destination_type(execution_target),
        destination_target=normalize_destination_target(destination_target),
        lifecycle_state="pending",
        writable=True,
        reopenable=False,
    )
    db.add(communication)
    order.communications.append(communication)
    return communication


async def refresh_remote_state(
    communication: OrderCommunication,
    *,
    raise_on_error: bool = False,
) -> tuple[str | None, bool, bool]:
    if not communication.bakery_ticket_id:
        return communication.remote_state, communication.writable, communication.reopenable
    try:
        remote = await sync_communication(communication.bakery_ticket_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to refresh remote communication state",
            extra={
                "order_id": communication.order_id,
                "communication_id": communication.id,
                "ticket_id": communication.bakery_ticket_id,
                "error": str(exc),
            },
        )
        if raise_on_error:
            raise
        remote_state = communication.remote_state
    else:
        remote_state = str(
            remote.state
            or (remote.communication_data or {}).get("state")
            or communication.remote_state
            or ""
        )
    writable, reopenable = determine_writeability(
        execution_target=communication.execution_target,
        remote_state=remote_state,
    )
    communication.remote_state = normalize_remote_state(remote_state) or communication.remote_state
    communication.writable = writable
    communication.reopenable = reopenable
    communication.updated_at = _now()
    return communication.remote_state, writable, reopenable


async def find_reusable_communication(
    db: AsyncSession,
    *,
    order: Order,
    execution_target: str,
    destination_target: str | None,
) -> OrderCommunication | None:
    if not is_ticket_capable_destination(execution_target):
        return None
    result = await db.execute(
        select(OrderCommunication)
        .join(Order, Order.id == OrderCommunication.order_id)
        .where(
            Order.fingerprint == order.fingerprint,
            Order.id != order.id,
            OrderCommunication.execution_target == normalize_destination_type(execution_target),
            OrderCommunication.destination_target
            == normalize_destination_target(destination_target),
            OrderCommunication.bakery_ticket_id.is_not(None),
        )
        .order_by(Order.updated_at.desc(), OrderCommunication.updated_at.desc())
    )
    candidates = result.scalars().all()
    for candidate in candidates:
        await refresh_remote_state(candidate)
        if candidate.writable or candidate.reopenable:
            return candidate
    return None


async def prepare_communication_context(
    db: AsyncSession,
    *,
    order_id: int,
    execution_target: str,
    destination_target: str | None,
    operation: str,
    execution_payload: dict[str, Any] | None = None,
) -> tuple[Order, OrderCommunication]:
    order = await load_order_with_communications(db, order_id=order_id, for_update=True)
    if order is None:
        raise ValueError(f"Order {order_id} not found")
    communication = await ensure_order_communication(
        db,
        order=order,
        execution_target=execution_target,
        destination_target=destination_target,
    )
    _remember_route_metadata(
        communication,
        execution_target=execution_target,
        execution_payload=execution_payload,
    )
    await refresh_remote_state(communication)
    if (
        operation == "open"
        and communication.bakery_ticket_id
        and not (communication.writable or communication.reopenable)
    ):
        communication.bakery_ticket_id = None
        communication.bakery_operation_id = None
        communication.lifecycle_state = "pending"
        communication.writable = True
        communication.reopenable = False
        communication.updated_at = _now()
    if not communication.bakery_ticket_id and is_ticket_capable_destination(execution_target):
        reusable = await find_reusable_communication(
            db,
            order=order,
            execution_target=execution_target,
            destination_target=destination_target,
        )
        if reusable is not None:
            communication.bakery_ticket_id = reusable.bakery_ticket_id
            communication.remote_state = reusable.remote_state
            communication.writable = reusable.writable
            communication.reopenable = reusable.reopenable
            communication.lifecycle_state = "reused"
            communication.updated_at = _now()
    _sync_legacy_order_fields(order)
    await db.flush()
    return order, communication


async def apply_execution_result(
    db: AsyncSession,
    *,
    order_id: int,
    execution_target: str,
    destination_target: str | None,
    operation: str,
    execution_ref: str | None,
    status: str,
    result_payload: dict[str, Any] | None,
    context_updates: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    order = await load_order_with_communications(db, order_id=order_id, for_update=True)
    if order is None:
        return
    communication = await ensure_order_communication(
        db,
        order=order,
        execution_target=execution_target,
        destination_target=destination_target,
    )
    updates = context_updates or {}
    ticket_id = str(updates.get("bakery_ticket_id") or communication.bakery_ticket_id or "").strip()
    if ticket_id:
        communication.bakery_ticket_id = ticket_id
    if execution_ref:
        communication.bakery_operation_id = execution_ref
    communication.lifecycle_state = status
    communication.last_error = error_message
    remote_state = None
    if isinstance(result_payload, dict):
        remote_state = (
            result_payload.get("state")
            or (result_payload.get("ticket_data") or {}).get("state")
            or (result_payload.get("provider_response") or {}).get("state")
        )
    if remote_state is not None:
        communication.remote_state = normalize_remote_state(remote_state)
    if status == "succeeded" and communication.bakery_ticket_id:
        await refresh_remote_state(communication)
    else:
        communication.writable, communication.reopenable = determine_writeability(
            execution_target=communication.execution_target,
            remote_state=communication.remote_state,
        )
        communication.updated_at = _now()
    _sync_legacy_order_fields(order)
    await db.flush()

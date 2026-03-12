#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Observability and communication activity endpoints for the mission-control UI."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.database import get_db
from api.models.models import AlertSuppression, Dish, Order, SuppressionSummary
from api.schemas.query_params import (
    CommunicationActivityQueryParams,
    ObservabilityActivityQueryParams,
    validate_query_params,
)
from api.schemas.schemas import CommunicationActivityRecord, ObservabilityActivityRecord
from api.services.communications import (
    is_ticket_capable_destination,
    normalize_destination_target,
    normalize_destination_type,
)
from api.services.suppression_service import suppression_status

router = APIRouter()


def _epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _destination_label(*, execution_target: str | None, destination_target: str | None) -> str:
    channel = normalize_destination_type(execution_target)
    destination = normalize_destination_target(destination_target)
    if destination:
        return f"{channel}:{destination}"
    return channel


async def _load_communication_activity(
    db: AsyncSession,
    *,
    status: str | None = None,
    channel: str | None = None,
    limit: int = 100,
) -> list[CommunicationActivityRecord]:
    normalized_channel = normalize_destination_type(channel) if channel else None
    rows: list[CommunicationActivityRecord] = []

    order_query = (
        select(Order)
        .options(joinedload(Order.communications))
        .where(
            or_(
                Order.communications.any(),
                Order.bakery_ticket_id.is_not(None),
                Order.bakery_operation_id.is_not(None),
            )
        )
        .order_by(Order.updated_at.desc())
        .limit(limit)
    )
    order_result = await db.execute(order_query)
    for order in order_result.unique().scalars().all():
        if order.communications:
            for communication in order.communications:
                current_channel = normalize_destination_type(communication.execution_target)
                if normalized_channel and current_channel != normalized_channel:
                    continue
                if status and status not in {
                    communication.lifecycle_state or "",
                    communication.remote_state or "",
                    order.processing_status or "",
                }:
                    continue

                ticket_id = (
                    communication.bakery_ticket_id
                    if is_ticket_capable_destination(communication.execution_target)
                    else None
                )
                provider_reference_id = (
                    None if ticket_id else (communication.bakery_ticket_id or None)
                )
                rows.append(
                    CommunicationActivityRecord(
                        communication_id=str(communication.id),
                        reference_type="incident",
                        reference_id=str(order.id),
                        reference_name=order.alert_group_name,
                        channel=current_channel,
                        destination=_destination_label(
                            execution_target=communication.execution_target,
                            destination_target=communication.destination_target,
                        ),
                        ticket_id=ticket_id,
                        provider_reference_id=provider_reference_id,
                        operation_id=communication.bakery_operation_id,
                        lifecycle_state=communication.lifecycle_state,
                        remote_state=communication.remote_state,
                        last_error=communication.last_error,
                        writable=communication.writable,
                        reopenable=communication.reopenable,
                        updated_at=communication.updated_at,
                    )
                )
            continue

        if normalized_channel and normalized_channel != "rackspace_core":
            continue
        if status and status not in {
            order.bakery_ticket_state or "",
            order.processing_status or "",
        }:
            continue
        rows.append(
            CommunicationActivityRecord(
                communication_id=f"legacy-order-{order.id}",
                reference_type="incident",
                reference_id=str(order.id),
                reference_name=order.alert_group_name,
                channel="rackspace_core",
                destination="rackspace_core",
                ticket_id=order.bakery_ticket_id,
                provider_reference_id=None,
                operation_id=order.bakery_operation_id,
                lifecycle_state=order.processing_status,
                remote_state=order.bakery_ticket_state,
                last_error=order.bakery_last_error,
                writable=None,
                reopenable=None,
                updated_at=order.updated_at,
            )
        )

    summary_query = (
        select(SuppressionSummary)
        .options(joinedload(SuppressionSummary.suppression))
        .order_by(SuppressionSummary.updated_at.desc())
        .limit(limit)
    )
    if status:
        summary_query = summary_query.where(SuppressionSummary.state == status)
    summary_result = await db.execute(summary_query)
    for item in summary_result.scalars().all():
        if normalized_channel and normalized_channel != "suppression_summary":
            continue
        rows.append(
            CommunicationActivityRecord(
                communication_id=f"suppression-summary-{item.id}",
                reference_type="suppression",
                reference_id=str(item.suppression_id),
                reference_name=item.suppression.name if item.suppression else None,
                channel="suppression_summary",
                destination=item.suppression.name if item.suppression else "Suppression summary",
                ticket_id=item.bakery_ticket_id,
                provider_reference_id=None,
                operation_id=item.bakery_create_operation_id or item.bakery_close_operation_id,
                lifecycle_state=item.state,
                remote_state=None,
                last_error=item.last_error,
                writable=None,
                reopenable=None,
                updated_at=item.updated_at,
            )
        )

    rows.sort(key=lambda item: item.updated_at or _epoch(), reverse=True)
    return rows


@router.get("/communications/activity", response_model=list[CommunicationActivityRecord])
async def get_communication_activity(
    params: CommunicationActivityQueryParams = Depends(
        validate_query_params(CommunicationActivityQueryParams)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CommunicationActivityRecord]:
    rows = await _load_communication_activity(
        db,
        status=params.status,
        channel=params.channel,
        limit=params.limit + params.offset,
    )
    return rows[params.offset : params.offset + params.limit]


@router.get("/observability/activity", response_model=list[ObservabilityActivityRecord])
async def get_observability_activity(
    params: ObservabilityActivityQueryParams = Depends(
        validate_query_params(ObservabilityActivityQueryParams)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ObservabilityActivityRecord]:
    records: list[ObservabilityActivityRecord] = []
    fetch_count = params.limit + params.offset

    order_result = await db.execute(
        select(Order).order_by(Order.updated_at.desc()).limit(fetch_count)
    )
    for order in order_result.scalars().all():
        instance = f" on {order.instance}" if order.instance else ""
        severity = order.severity or "unknown severity"
        records.append(
            ObservabilityActivityRecord(
                type="incident",
                status=order.processing_status,
                title=order.alert_group_name,
                summary=f"{order.alert_status} | {severity}{instance}",
                timestamp=order.updated_at,
                target_kind="incident",
                target_id=str(order.id),
                link_hint=f"/incidents/{order.id}",
                metadata={
                    "severity": order.severity,
                    "instance": order.instance,
                    "counter": order.counter,
                },
            )
        )

    dish_result = await db.execute(
        select(Dish)
        .options(joinedload(Dish.recipe), joinedload(Dish.order))
        .order_by(Dish.updated_at.desc())
        .limit(fetch_count)
    )
    for dish in dish_result.unique().scalars().all():
        recipe_name = dish.recipe.name if dish.recipe else f"Workflow #{dish.recipe_id}"
        target_link = f"/activity?dish={dish.id}"
        if dish.order_id:
            target_link = f"/incidents/{dish.order_id}?dish={dish.id}"
        records.append(
            ObservabilityActivityRecord(
                type="automation",
                status=dish.processing_status,
                title=f"{recipe_name} run",
                summary=f"{dish.run_phase} phase | execution {dish.execution_ref or 'pending'}",
                timestamp=dish.updated_at,
                target_kind="activity",
                target_id=str(dish.id),
                link_hint=target_link,
                metadata={
                    "order_id": dish.order_id,
                    "run_phase": dish.run_phase,
                    "execution_ref": dish.execution_ref,
                },
            )
        )

    communication_rows = await _load_communication_activity(db, limit=fetch_count)
    for item in communication_rows:
        link_hint = "/communications"
        if item.reference_type == "incident":
            link_hint = f"/incidents/{item.reference_id}?communication={item.communication_id}"
        elif item.reference_type == "suppression":
            link_hint = f"/suppressions?suppression={item.reference_id}"
        reference_name = item.reference_name or item.reference_id
        records.append(
            ObservabilityActivityRecord(
                type="communication",
                status=item.remote_state or item.lifecycle_state or "unknown",
                title=f"{item.channel} route for {reference_name}",
                summary=item.destination or item.ticket_id or item.provider_reference_id,
                timestamp=item.updated_at,
                target_kind="communication",
                target_id=item.communication_id,
                link_hint=link_hint,
                metadata={
                    "reference_type": item.reference_type,
                    "reference_id": item.reference_id,
                    "ticket_id": item.ticket_id,
                    "provider_reference_id": item.provider_reference_id,
                    "last_error": item.last_error,
                },
            )
        )

    suppression_result = await db.execute(
        select(AlertSuppression).order_by(AlertSuppression.updated_at.desc()).limit(fetch_count)
    )
    for suppression in suppression_result.scalars().all():
        status = suppression_status(suppression)
        records.append(
            ObservabilityActivityRecord(
                type="suppression",
                status=status,
                title=suppression.name,
                summary=suppression.reason
                or f"{suppression.scope} suppression window until {suppression.ends_at.isoformat()}",
                timestamp=suppression.updated_at,
                target_kind="suppression",
                target_id=str(suppression.id),
                link_hint=f"/suppressions?suppression={suppression.id}",
                metadata={
                    "scope": suppression.scope,
                    "summary_ticket_enabled": suppression.summary_ticket_enabled,
                },
            )
        )

    if params.type:
        requested_type = params.type.strip().lower()
        records = [item for item in records if item.type.lower() == requested_type]

    records.sort(key=lambda item: item.timestamp or _epoch(), reverse=True)
    return records[params.offset : params.offset + params.limit]

#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for suppression windows and suppression observability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import (
    AlertSuppression,
    AlertSuppressionMatcher,
    Dish,
    Order,
    SuppressionSummary,
)
from api.schemas.query_params import (
    BakeryOperationQueryParams,
    SuppressedActivityQueryParams,
    SuppressionQueryParams,
    validate_query_params,
)
from api.schemas.schemas import (
    BakeryOperationRecord,
    ObservabilityBakerySummary,
    ObservabilityFailuresSummary,
    ObservabilityHealthSummary,
    ObservabilityOverviewResponse,
    ObservabilityQueueSummary,
    ObservabilitySuppressionsSummary,
    ObservabilityTopError,
    SuppressedActivityResponse,
    SuppressionCreate,
    SuppressionDetailResponse,
    SuppressionLifecycleResponse,
    SuppressionMatcher,
    SuppressionResponse,
    SuppressionSummaryResponse,
    SuppressionStatsResponse,
    SuppressionUpdate,
)
from api.services.suppression_service import (
    compute_suppression_stats,
    count_active_suppressions,
    finalize_expired_suppressions,
    get_suppression,
    list_suppression_activity,
    list_suppressions,
    suppression_status,
)
from api.types import SuppressionMatcherOperator, SuppressionScope, SuppressionStatus

router = APIRouter()
logger = get_logger(__name__)


def _to_matcher_response(matchers: list[AlertSuppressionMatcher]) -> list[SuppressionMatcher]:
    return [
        SuppressionMatcher(
            label_key=m.label_key,
            operator=cast(SuppressionMatcherOperator, m.operator),
            value=m.value,
        )
        for m in matchers
    ]


def _to_suppression_response(item: AlertSuppression) -> SuppressionResponse:
    status = cast(SuppressionStatus, suppression_status(item))
    return SuppressionResponse(
        id=item.id,
        name=item.name,
        reason=item.reason,
        scope=cast(SuppressionScope, item.scope),
        status=status,
        enabled=item.enabled,
        starts_at=item.starts_at,
        ends_at=item.ends_at,
        canceled_at=item.canceled_at,
        created_by=item.created_by,
        summary_ticket_enabled=item.summary_ticket_enabled,
        created_at=item.created_at,
        updated_at=item.updated_at,
        matchers=_to_matcher_response(item.matchers),
    )


@router.get("/suppressions", response_model=list[SuppressionResponse])
async def get_suppressions(
    request: Request,
    params: SuppressionQueryParams = Depends(validate_query_params(SuppressionQueryParams)),
    db: AsyncSession = Depends(get_db),
) -> list[SuppressionResponse]:
    req_id = request.state.req_id
    rows = await list_suppressions(
        db=db,
        status=params.status,
        enabled=params.enabled,
        scope=params.scope,
        limit=params.limit,
        offset=params.offset,
    )
    logger.debug("Fetched suppressions", extra={"req_id": req_id, "count": len(rows)})
    return [_to_suppression_response(row) for row in rows]


@router.post("/suppressions", response_model=SuppressionResponse, status_code=201)
async def create_suppression(
    request: Request,
    payload: SuppressionCreate,
    db: AsyncSession = Depends(get_db),
) -> SuppressionResponse:
    req_id = request.state.req_id
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be greater than starts_at")
    if payload.scope == "matchers" and not payload.matchers:
        raise HTTPException(status_code=400, detail="matchers required when scope=matchers")

    suppression = AlertSuppression(
        name=payload.name,
        reason=payload.reason,
        scope=payload.scope,
        enabled=payload.enabled,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        created_by=payload.created_by,
        summary_ticket_enabled=payload.summary_ticket_enabled,
    )
    db.add(suppression)
    await db.flush()

    for matcher in payload.matchers:
        db.add(
            AlertSuppressionMatcher(
                suppression_id=suppression.id,
                label_key=matcher.label_key,
                operator=matcher.operator,
                value=matcher.value,
            )
        )
    await db.commit()
    refreshed = await get_suppression(db, suppression.id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Failed to create suppression")
    logger.info(
        "Created suppression",
        extra={"req_id": req_id, "suppression_id": refreshed.id, "name": refreshed.name},
    )
    return _to_suppression_response(refreshed)


@router.get("/suppressions/{suppression_id}", response_model=SuppressionDetailResponse)
async def get_suppression_by_id(
    request: Request,
    suppression_id: int,
    db: AsyncSession = Depends(get_db),
) -> SuppressionDetailResponse:
    req_id = request.state.req_id
    suppression = await get_suppression(db, suppression_id)
    if not suppression:
        raise HTTPException(status_code=404, detail="Suppression not found")

    stats = await compute_suppression_stats(db, suppression.id)
    response = _to_suppression_response(suppression)
    logger.debug(
        "Fetched suppression detail", extra={"req_id": req_id, "suppression_id": suppression_id}
    )
    return SuppressionDetailResponse(
        **response.model_dump(),
        counters=SuppressionStatsResponse(
            suppression_id=suppression.id,
            total_suppressed=stats["total_suppressed"],
            by_alertname=stats["by_alertname"],
            by_severity=stats["by_severity"],
            first_seen_at=stats["first_seen_at"],
            last_seen_at=stats["last_seen_at"],
        ),
        summary=(
            SuppressionSummaryResponse.model_validate(suppression.summary)
            if suppression.summary
            else None
        ),
    )


@router.patch("/suppressions/{suppression_id}", response_model=SuppressionResponse)
async def patch_suppression(
    request: Request,
    suppression_id: int,
    payload: SuppressionUpdate,
    db: AsyncSession = Depends(get_db),
) -> SuppressionResponse:
    req_id = request.state.req_id
    suppression = await get_suppression(db, suppression_id)
    if not suppression:
        raise HTTPException(status_code=404, detail="Suppression not found")

    changes = payload.model_dump(exclude_unset=True)
    if "ends_at" in changes and changes["ends_at"] <= suppression.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be greater than starts_at")

    for field in ("name", "ends_at", "reason", "enabled"):
        if field in changes:
            setattr(suppression, field, changes[field])

    if "matchers" in changes:
        await db.execute(
            delete(AlertSuppressionMatcher).where(
                AlertSuppressionMatcher.suppression_id == suppression.id
            )
        )
        for matcher in payload.matchers or []:
            db.add(
                AlertSuppressionMatcher(
                    suppression_id=suppression.id,
                    label_key=matcher.label_key,
                    operator=matcher.operator,
                    value=matcher.value,
                )
            )

    suppression.updated_at = datetime.now(timezone.utc)
    await db.commit()
    refreshed = await get_suppression(db, suppression.id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Failed to update suppression")
    logger.info("Updated suppression", extra={"req_id": req_id, "suppression_id": suppression_id})
    return _to_suppression_response(refreshed)


@router.post("/suppressions/{suppression_id}/cancel", response_model=SuppressionResponse)
async def cancel_suppression(
    request: Request,
    suppression_id: int,
    db: AsyncSession = Depends(get_db),
) -> SuppressionResponse:
    req_id = request.state.req_id
    suppression = await get_suppression(db, suppression_id)
    if not suppression:
        raise HTTPException(status_code=404, detail="Suppression not found")

    suppression.canceled_at = datetime.now(timezone.utc)
    suppression.enabled = False
    suppression.updated_at = datetime.now(timezone.utc)
    await db.commit()
    refreshed = await get_suppression(db, suppression.id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Failed to cancel suppression")
    logger.info("Canceled suppression", extra={"req_id": req_id, "suppression_id": suppression_id})
    return _to_suppression_response(refreshed)


@router.get("/suppressions/{suppression_id}/stats", response_model=SuppressionStatsResponse)
async def get_suppression_stats(
    suppression_id: int,
    db: AsyncSession = Depends(get_db),
) -> SuppressionStatsResponse:
    suppression = await get_suppression(db, suppression_id)
    if not suppression:
        raise HTTPException(status_code=404, detail="Suppression not found")
    stats = await compute_suppression_stats(db, suppression_id)
    return SuppressionStatsResponse(
        suppression_id=suppression_id,
        total_suppressed=stats["total_suppressed"],
        by_alertname=stats["by_alertname"],
        by_severity=stats["by_severity"],
        first_seen_at=stats["first_seen_at"],
        last_seen_at=stats["last_seen_at"],
    )


@router.get("/activity/suppressed", response_model=list[SuppressedActivityResponse])
async def get_suppressed_activity(
    params: SuppressedActivityQueryParams = Depends(
        validate_query_params(SuppressedActivityQueryParams)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[SuppressedActivityResponse]:
    rows = await list_suppression_activity(
        db=db,
        suppression_id=params.suppression_id,
        limit=params.limit,
        offset=params.offset,
    )
    return [SuppressedActivityResponse.model_validate(row) for row in rows]


@router.post("/suppressions/run-lifecycle", response_model=SuppressionLifecycleResponse)
async def run_suppression_lifecycle(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuppressionLifecycleResponse:
    req_id = request.state.req_id
    finalized = await finalize_expired_suppressions(db, req_id=req_id)
    return SuppressionLifecycleResponse(status="ok", finalized=finalized)


@router.get("/observability/overview", response_model=ObservabilityOverviewResponse)
async def get_observability_overview(
    db: AsyncSession = Depends(get_db),
) -> ObservabilityOverviewResponse:
    active_suppressions = await count_active_suppressions(db)

    order_new = await db.scalar(
        select(func.count(Order.id)).where(Order.processing_status == "new")
    )
    order_processing = await db.scalar(
        select(func.count(Order.id)).where(Order.processing_status == "processing")
    )
    failed_orders = await db.scalar(
        select(func.count(Order.id)).where(Order.processing_status == "failed")
    )
    failed_dishes = await db.scalar(
        select(func.count(Dish.id)).where(Dish.processing_status == "failed")
    )

    bakery_failures = await db.scalar(
        select(func.count(SuppressionSummary.id)).where(SuppressionSummary.state == "failed")
    )
    order_ticket_dead_letters = await db.scalar(
        select(func.count(Order.id)).where(
            Order.bakery_permanent_failure.is_(True),
            Order.is_active.is_(True),
        )
    )

    top_errors_result = await db.execute(
        select(Dish.error_message, func.count(Dish.id))
        .where(Dish.error_message.is_not(None), Dish.error_message != "")
        .group_by(Dish.error_message)
        .order_by(func.count(Dish.id).desc())
        .limit(5)
    )
    top_errors = [
        {"error": str(error), "count": int(count)}
        for error, count in top_errors_result.all()
        if error is not None
    ]

    retrying_operations = await db.scalar(
        select(func.count(SuppressionSummary.id)).where(
            SuppressionSummary.state.in_(["pending", "created"])
        )
    )
    dead_letter_count = await db.scalar(
        select(func.count(SuppressionSummary.id)).where(SuppressionSummary.state == "failed")
    )
    runbook_hints: list[str] = []
    if int(failed_dishes or 0) > 0:
        runbook_hints.append(
            "Failed dishes detected. Check StackStorm execution/task errors in Incident Timeline."
        )
    if int(bakery_failures or 0) > 0:
        runbook_hints.append(
            "Bakery summary failures detected. Verify Bakery auth, endpoint reachability, and operation status."
        )
    if int(order_ticket_dead_letters or 0) > 0:
        runbook_hints.append(
            "Order-level Bakery dead letters detected. Verify provider-required labels "
            "(for example coreAccountID) and replay handling."
        )
    if int(order_new or 0) > 20:
        runbook_hints.append(
            "Order queue backlog is high. Check prep-chef throughput and API latency."
        )

    return ObservabilityOverviewResponse(
        health=ObservabilityHealthSummary(status="ok"),
        queue=ObservabilityQueueSummary(
            orders_new=int(order_new or 0),
            orders_processing=int(order_processing or 0),
        ),
        failures=ObservabilityFailuresSummary(
            orders_failed=int(failed_orders or 0),
            dishes_failed=int(failed_dishes or 0),
            top_errors=[ObservabilityTopError.model_validate(item) for item in top_errors],
            runbook_hints=runbook_hints,
        ),
        bakery=ObservabilityBakerySummary(
            summary_failures=int(bakery_failures or 0),
            order_dead_letters=int(order_ticket_dead_letters or 0),
        ),
        suppressions=ObservabilitySuppressionsSummary(
            active=int(active_suppressions),
            retrying_operations=int(retrying_operations or 0),
            dead_letter=int(dead_letter_count or 0),
        ),
    )


@router.get("/ticketing/bakery", response_model=list[BakeryOperationRecord])
async def get_bakery_ticketing_history(
    params: BakeryOperationQueryParams = Depends(validate_query_params(BakeryOperationQueryParams)),
    db: AsyncSession = Depends(get_db),
) -> list[BakeryOperationRecord]:
    rows: list[BakeryOperationRecord] = []

    summary_query = select(SuppressionSummary).order_by(SuppressionSummary.updated_at.desc())
    if params.status:
        summary_query = summary_query.where(SuppressionSummary.state == params.status)
    summary_result = await db.execute(summary_query.limit(params.limit).offset(params.offset))
    for item in summary_result.scalars().all():
        rows.append(
            BakeryOperationRecord(
                source="suppression_summary",
                reference_id=str(item.suppression_id),
                reference_type="suppression",
                reference_name=item.suppression.name if item.suppression else None,
                channel="suppression_summary",
                destination=item.suppression.name if item.suppression else "Suppression summary",
                ticket_id=item.bakery_ticket_id,
                provider_reference_id=None,
                operation_id=item.bakery_create_operation_id or item.bakery_close_operation_id,
                status=item.state,
                last_error=item.last_error,
                updated_at=item.updated_at,
                details={
                    "create_operation_id": item.bakery_create_operation_id,
                    "close_operation_id": item.bakery_close_operation_id,
                    "total_suppressed": item.total_suppressed,
                },
            )
        )

    order_query = (
        select(Order)
        .options(joinedload(Order.communications))
        .where(
            or_(
                Order.bakery_ticket_id.is_not(None),
                Order.bakery_operation_id.is_not(None),
                Order.communications.any(),
            )
        )
    )
    if params.status:
        order_query = order_query.where(
            or_(
                Order.processing_status == params.status, Order.bakery_ticket_state == params.status
            )
        )
    order_result = await db.execute(
        order_query.order_by(Order.updated_at.desc()).limit(params.limit)
    )
    for order in order_result.unique().scalars().all():
        if order.communications:
            for communication in order.communications:
                if params.status and params.status not in {
                    communication.lifecycle_state or "",
                    communication.remote_state or "",
                    order.processing_status or "",
                }:
                    continue
                rows.append(
                    BakeryOperationRecord(
                        source="order",
                        reference_id=str(order.id),
                        reference_type="incident",
                        reference_name=order.alert_group_name,
                        channel=communication.execution_target,
                        destination=(
                            f"{communication.execution_target}:{communication.destination_target}"
                            if communication.destination_target
                            else communication.execution_target
                        ),
                        ticket_id=communication.bakery_ticket_id,
                        provider_reference_id=(
                            None
                            if communication.execution_target == "rackspace_core"
                            else communication.bakery_ticket_id
                        ),
                        operation_id=communication.bakery_operation_id,
                        status=communication.lifecycle_state or communication.remote_state,
                        execution_target=communication.execution_target,
                        destination_target=communication.destination_target,
                        remote_state=communication.remote_state,
                        writable=communication.writable,
                        reopenable=communication.reopenable,
                        last_error=communication.last_error,
                        updated_at=communication.updated_at,
                        details={
                            "alert_group_name": order.alert_group_name,
                            "req_id": order.req_id,
                            "last_error": communication.last_error,
                            "order_processing_status": order.processing_status,
                        },
                    )
                )
        elif order.bakery_ticket_id or order.bakery_operation_id:
            rows.append(
                BakeryOperationRecord(
                    source="order",
                    reference_id=str(order.id),
                    reference_type="incident",
                    reference_name=order.alert_group_name,
                    channel="rackspace_core",
                    destination="rackspace_core",
                    ticket_id=order.bakery_ticket_id,
                    provider_reference_id=None,
                    operation_id=order.bakery_operation_id,
                    status=order.bakery_ticket_state or order.processing_status,
                    last_error=order.bakery_last_error,
                    updated_at=order.updated_at,
                    details={
                        "alert_group_name": order.alert_group_name,
                        "req_id": order.req_id,
                        "permanent_failure": order.bakery_permanent_failure,
                        "last_error": order.bakery_last_error,
                    },
                )
            )

    rows.sort(
        key=lambda item: item.updated_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    return rows[: params.limit]

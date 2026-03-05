#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Order management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, asc, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import Any, List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.statuses import ORDER_TERMINAL_PROCESSING_STATUSES
from api.models.models import Dish, DishIngredient, Order, Recipe, RecipeIngredient, Ingredient
from api.schemas.schemas import (
    IncidentTimelineEvent,
    IncidentTimelineResponse,
    OrderCreate,
    OrderResponse,
    OrderUpdate,
)
from api.schemas.query_params import OrderQueryParams, validate_query_params
from api.services.bakery_client import get_operation
from api.services.execution_orchestrator import ExecutionOrchestrator, get_execution_orchestrator
from api.services.execution_types import ExecutionContext
from api.services.fallback_recipe import ensure_fallback_recipe
from api.validation.execution import validate_runtime_execution_payload

router = APIRouter()
logger = get_logger(__name__)


def _is_phase_eligible(step_phase: str | None, target_phase: str) -> bool:
    normalized = (step_phase or "both").lower()
    return normalized == "both" or normalized == target_phase


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _render_resolve_payload(
    *,
    execution_payload: dict[str, Any] | None,
    execution_parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = execution_payload or {}
    template = payload.get("template")
    if not isinstance(template, dict):
        return {}
    rendered = dict(template)
    context = payload.get("context")
    if isinstance(context, dict):
        rendered["context"] = _deep_merge(
            rendered.get("context") if isinstance(rendered.get("context"), dict) else {},
            context,
        )
    if execution_parameters:
        rendered = _deep_merge(rendered, execution_parameters)
    return rendered


@router.get("/orders", response_model=List[OrderResponse])
async def fetch_orders(
    request: Request,
    params: OrderQueryParams = Depends(validate_query_params(OrderQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Get orders with optional filtering.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/resolving/complete/failed/canceled)
    - alert_status: Filter by alert status (firing/resolved)
    - req_id: Filter by request ID
    - alert_group_name: Filter by alert group name
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "Fetching orders",
        extra={
            "req_id": request_id,
            "processing_status": params.processing_status,
            "alert_status": params.alert_status,
            "filter_req_id": params.req_id,
            "alert_group_name": params.alert_group_name,
            "limit": params.limit,
            "offset": params.offset,
        },
    )

    query = select(Order)

    if params.processing_status:
        query = query.where(Order.processing_status == params.processing_status)
    if params.alert_status:
        query = query.where(Order.alert_status == params.alert_status)
    if params.req_id:
        query = query.where(Order.req_id == params.req_id)
    if params.alert_group_name:
        query = query.where(Order.alert_group_name == params.alert_group_name)

    if params.processing_status and params.processing_status == "new":
        query = query.order_by(asc(Order.created_at))
    else:
        query = query.order_by(desc(Order.created_at))

    query = query.limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    orders = result.scalars().all()

    logger.debug(
        "Orders fetched successfully",
        extra={"req_id": request_id, "count": len(orders)},
    )

    return orders


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(request: Request, payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    """Create an order manually (non-Alertmanager ingestion)."""
    req_id = request.state.req_id

    logger.info(
        "Creating order",
        extra={
            "req_id": req_id,
            "order_req_id": payload.req_id,
            "alert_status": payload.alert_status,
            "group_name": payload.alert_group_name,
        },
    )

    create_data = payload.model_dump()
    # Generated by DB; ignore user input to avoid writes to computed column.
    create_data.pop("fingerprint_when_active", None)
    order = Order(**create_data)
    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info(
        "Order created successfully",
        extra={"req_id": req_id, "order_id": order.id},
    )

    return order


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(request: Request, order_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve a specific order by ID."""
    req_id = request.state.req_id

    logger.debug("Fetching order by ID", extra={"req_id": req_id, "order_id": order_id})

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()

    if not order:
        logger.warning("Order not found", extra={"req_id": req_id, "order_id": order_id})
        raise HTTPException(status_code=404, detail="Order not found")

    return order


@router.put("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    request: Request, order_id: int, payload: OrderUpdate, db: AsyncSession = Depends(get_db)
):
    """Used by Timer to set status to 'complete' or Chef to 'processing'."""
    req_id = request.state.req_id

    logger.info("Updating order", extra={"req_id": req_id, "order_id": order_id})

    order: Order | None = None
    async with db.begin():
        result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
        order = result.scalars().first()
        if not order:
            logger.warning(
                "Order not found for update",
                extra={"req_id": req_id, "order_id": order_id},
            )
            raise HTTPException(status_code=404, detail="Order not found")

        update_data = payload.model_dump(exclude_unset=True)
        # Generated by DB; ignore user input to avoid writes to computed column.
        update_data.pop("fingerprint_when_active", None)

        # Check terminal state transitions BEFORE applying updates
        if update_data.get("processing_status") in ORDER_TERMINAL_PROCESSING_STATUSES:
            if update_data.get("is_active") is True:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot set is_active=true with terminal processing_status",
                )
            # Check if order is already in a different terminal status
            if (
                order.processing_status in ORDER_TERMINAL_PROCESSING_STATUSES
                and order.processing_status != update_data.get("processing_status")
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"Order already in terminal status {order.processing_status}",
                )
            order.is_active = False

        # Apply updates after validation
        for key, value in update_data.items():
            setattr(order, key, value)

        order.updated_at = datetime.now(timezone.utc)

    if order is None:
        raise HTTPException(status_code=500, detail="Order update failed")
    await db.refresh(order)

    logger.info(
        "Order updated successfully",
        extra={
            "req_id": req_id,
            "order_id": order_id,
            "fields_updated": len(update_data),
            "new_status": order.processing_status,
        },
    )

    return order


@router.post("/orders/{order_id}/resolve", response_model=OrderResponse)
async def resolve_order(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
    orchestrator: ExecutionOrchestrator = Depends(get_execution_orchestrator),
):
    """Resolve-phase orchestration for an order using resolve-eligible recipe steps only."""
    req_id = request.state.req_id
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with db.begin():
        order_result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
        order = order_result.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.processing_status == "complete":
            return order
        if order.processing_status != "resolving":
            raise HTTPException(
                status_code=409,
                detail=f"Order must be in resolving status (current={order.processing_status})",
            )

        recipe_result = await db.execute(
            select(Recipe)
            .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
            .where(Recipe.name == order.alert_group_name, Recipe.enabled.is_(True))
            .with_for_update()
        )
        recipe = recipe_result.unique().scalars().first()
        if not recipe:
            catch_all_name = (settings.catch_all_recipe_name or "").strip()
            if catch_all_name:
                await ensure_fallback_recipe(db, req_id=req_id)
                fallback_result = await db.execute(
                    select(Recipe)
                    .options(
                        joinedload(Recipe.recipe_ingredients).joinedload(
                            RecipeIngredient.ingredient
                        )
                    )
                    .where(Recipe.name == catch_all_name, Recipe.enabled.is_(True))
                    .with_for_update()
                )
                recipe = fallback_result.unique().scalars().first()
        if not recipe:
            raise HTTPException(status_code=404, detail="No recipe available for resolve flow")

        dish_result = await db.execute(
            select(Dish)
            .where(Dish.order_id == order.id)
            .order_by(Dish.created_at.desc())
            .with_for_update()
        )
        dish = dish_result.scalars().first()

        if dish is None:
            expected_result = await db.execute(
                select(func.coalesce(func.sum(Ingredient.expected_duration_sec), 0))
                .select_from(RecipeIngredient)
                .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
                .where(
                    RecipeIngredient.recipe_id == recipe.id,
                    RecipeIngredient.run_phase.in_(("resolving", "both")),
                )
            )
            expected_duration_sec = expected_result.scalar() or 0

            dish = Dish(
                req_id=order.req_id,
                order_id=order.id,
                recipe_id=recipe.id,
                processing_status="complete",
                execution_status="succeeded",
                started_at=now,
                completed_at=now,
                expected_duration_sec=expected_duration_sec,
                actual_duration_sec=0,
            )
            db.add(dish)
            await db.flush()

        existing_result = await db.execute(
            select(DishIngredient)
            .where(DishIngredient.dish_id == dish.id, DishIngredient.deleted.is_(False))
            .with_for_update()
        )
        existing_by_recipe_ingredient_id = {
            row.recipe_ingredient_id: row
            for row in existing_result.scalars().all()
            if row.recipe_ingredient_id is not None
        }

        resolve_steps = sorted(recipe.recipe_ingredients, key=lambda item: item.step_order)
        for ri in resolve_steps:
            if ri.ingredient is None:
                continue
            if not _is_phase_eligible(ri.run_phase, "resolving"):
                continue
            if (ri.ingredient.execution_purpose or "").lower() != "comms":
                continue

            task_suffix = (ri.ingredient.task_key_template or "task").replace(".", "_")
            task_key = f"step_{ri.step_order}_{task_suffix}"
            params = dict(ri.ingredient.execution_parameters or {})
            if ri.execution_parameters_override:
                params.update(ri.execution_parameters_override)
            validation_error = validate_runtime_execution_payload(
                execution_engine=ri.ingredient.execution_engine,
                execution_purpose=ri.ingredient.execution_purpose,
                execution_target=ri.ingredient.execution_target,
                execution_payload=ri.ingredient.execution_payload,
                execution_parameters=params or None,
            )

            dish_ingredient = existing_by_recipe_ingredient_id.get(ri.id)
            if dish_ingredient is None:
                dish_ingredient = DishIngredient(
                    dish_id=dish.id,
                    recipe_ingredient_id=ri.id,
                    task_key=task_key,
                    execution_engine=ri.ingredient.execution_engine,
                    execution_target=ri.ingredient.execution_target,
                    execution_status="pending",
                    execution_parameters=params or None,
                )
                db.add(dish_ingredient)
                await db.flush()

            if validation_error:
                dish_ingredient.execution_payload = ri.ingredient.execution_payload
                dish_ingredient.execution_status = "failed"
                dish_ingredient.error_message = validation_error
                dish_ingredient.completed_at = now
                if (ri.ingredient.on_failure or "stop").lower() != "continue":
                    order.processing_status = "failed"
                    order.is_active = False
                    order.updated_at = now
                    dish.processing_status = "failed"
                    dish.execution_status = "failed"
                    dish.error_message = validation_error
                    dish.completed_at = now
                    dish.updated_at = now
                    break
                continue

            rendered_payload = _render_resolve_payload(
                execution_payload=ri.ingredient.execution_payload,
                execution_parameters=params or None,
            )

            dish_ingredient.execution_payload = rendered_payload
            dish_ingredient.execution_parameters = params or None
            dish_ingredient.execution_status = "running"
            dish_ingredient.started_at = datetime.now(timezone.utc)
            dish_ingredient.error_message = None
            dish_ingredient.result = None

            try:
                execution_result = await orchestrator.execute(
                    ExecutionContext(
                        engine=ri.ingredient.execution_engine,
                        req_id=req_id,
                        execution_payload=rendered_payload,
                        execution_parameters=params or None,
                        retry_count=getattr(ri.ingredient, "retry_count", 0),
                        retry_delay=getattr(ri.ingredient, "retry_delay", 5),
                        timeout_duration_sec=getattr(ri.ingredient, "timeout_duration_sec", 300),
                        context={
                            "order_id": order.id,
                            "recipe_ingredient_id": ri.id,
                            "bakery_ticket_id": order.bakery_ticket_id,
                        },
                        execution_target=ri.ingredient.execution_target,
                    )
                )
                if execution_result.context_updates.get("bakery_ticket_id"):
                    order.bakery_ticket_id = str(
                        execution_result.context_updates["bakery_ticket_id"]
                    )
                dish_ingredient.execution_ref = execution_result.execution_ref
                dish_ingredient.result = execution_result.raw or execution_result.result
                dish_ingredient.completed_at = datetime.now(timezone.utc)
                if execution_result.status == "succeeded":
                    dish_ingredient.execution_status = "succeeded"
                else:
                    dish_ingredient.execution_status = "failed"
                    dish_ingredient.error_message = (
                        execution_result.error_message
                        or "Execution failed without adapter error_message"
                    )
            except Exception as exc:  # noqa: BLE001
                dish_ingredient.execution_status = "failed"
                dish_ingredient.error_message = str(exc)
                dish_ingredient.completed_at = datetime.now(timezone.utc)

            if (dish_ingredient.execution_status or "").lower() != "succeeded":
                if (ri.ingredient.on_failure or "stop").lower() != "continue":
                    order.processing_status = "failed"
                    order.is_active = False
                    order.updated_at = now
                    dish.processing_status = "failed"
                    dish.execution_status = "failed"
                    dish.error_message = dish_ingredient.error_message
                    dish.completed_at = now
                    dish.updated_at = now
                    break

        if order.processing_status != "failed":
            order.processing_status = "complete"
            order.is_active = False
            dish.processing_status = "complete"
            dish.execution_status = "succeeded"
            dish.completed_at = now
            order.updated_at = now
            dish.updated_at = now

    await db.refresh(order)
    logger.info(
        "Order resolve flow completed",
        extra={
            "req_id": req_id,
            "order_id": order_id,
            "processing_status": order.processing_status,
        },
    )
    return order


@router.get("/orders/{order_id}/timeline", response_model=IncidentTimelineResponse)
async def get_order_timeline(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> IncidentTimelineResponse:
    req_id = request.state.req_id
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    events: list[IncidentTimelineEvent] = [
        IncidentTimelineEvent(
            timestamp=order.created_at,
            event_type="order",
            status=order.processing_status,
            title=f"Order {order.id} received",
            details={
                "alert_group_name": order.alert_group_name,
                "alert_status": order.alert_status,
                "counter": order.counter,
            },
            correlation_ids={
                "req_id": order.req_id,
                "fingerprint": order.fingerprint,
            },
        )
    ]

    dishes_result = await db.execute(
        select(Dish).where(Dish.order_id == order.id).order_by(Dish.created_at.asc())
    )
    dishes = dishes_result.scalars().all()
    for dish in dishes:
        events.append(
            IncidentTimelineEvent(
                timestamp=dish.started_at or dish.created_at,
                event_type="dish",
                status=dish.processing_status,
                title=f"Dish {dish.id} {dish.processing_status}",
                details={
                    "status": dish.execution_status,
                    "error_message": dish.error_message,
                },
                correlation_ids={
                    "dish_id": str(dish.id),
                    "execution_ref": dish.execution_ref or "",
                },
            )
        )
        ingredient_result = await db.execute(
            select(DishIngredient)
            .where(DishIngredient.dish_id == dish.id, DishIngredient.deleted.is_(False))
            .order_by(DishIngredient.created_at.asc())
        )
        for ingredient in ingredient_result.scalars().all():
            events.append(
                IncidentTimelineEvent(
                    timestamp=ingredient.started_at or ingredient.created_at,
                    event_type="task",
                    status=ingredient.execution_status or "unknown",
                    title=f"Task {ingredient.task_key or 'unknown'}",
                    details={
                        "error_message": ingredient.error_message,
                    },
                    correlation_ids={
                        "execution_ref": ingredient.execution_ref or "",
                        "dish_ingredient_id": str(ingredient.id),
                    },
                )
            )

    if order.bakery_ticket_id or order.bakery_operation_id:
        bakery_status = "unknown"
        bakery_details = {}
        if order.bakery_operation_id:
            try:
                op_payload = await get_operation(order.bakery_operation_id)
                bakery_status = str(op_payload.get("status") or "unknown")
                bakery_details = op_payload
            except Exception:
                bakery_status = "unavailable"
        events.append(
            IncidentTimelineEvent(
                timestamp=order.updated_at,
                event_type="bakery",
                status=bakery_status,
                title="Bakery operation tracked on order",
                details=bakery_details,
                correlation_ids={
                    "bakery_ticket_id": order.bakery_ticket_id or "",
                    "bakery_operation_id": order.bakery_operation_id or "",
                    "bakery_ticket_state": order.bakery_ticket_state or "",
                },
            )
        )

    events.sort(
        key=lambda item: item.timestamp or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=False,
    )
    logger.debug(
        "Built incident timeline",
        extra={"req_id": req_id, "order_id": order_id, "event_count": len(events)},
    )
    return IncidentTimelineResponse(order=OrderResponse.model_validate(order), events=events)

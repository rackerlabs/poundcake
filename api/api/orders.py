#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Order management."""

from typing import Any, List, Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.api.auth import require_auth_if_enabled
from api.core.config import get_settings
from api.core.database import get_db
from api.core.logging import get_logger
from api.core.statuses import ORDER_TERMINAL_PROCESSING_STATUSES
from api.models.models import Dish, DishIngredient, Order, Recipe, RecipeIngredient
from api.schemas.schemas import (
    IncidentTimelineEvent,
    IncidentTimelineResponse,
    OrderCreate,
    OrderDispatchResponse,
    OrderResponse,
    OrderUpdate,
)
from api.schemas.query_params import OrderQueryParams, validate_query_params
from api.services.bakery_client import get_operation
from api.services.communications_policy import (
    get_global_policy_recipe_for_dispatch,
    get_recipe_local_routes,
    global_policy_configured,
    policy_has_enabled_routes,
)
from api.services.fallback_recipe import ensure_fallback_recipe
from api.services.incident_reconciliation import reconcile_order
from api.services.dish_planner import expected_duration_for_phase, seed_dish_ingredients_for_phase

router = APIRouter()
logger = get_logger(__name__)
GLOBAL_COMMS_INHERIT_PHASES = {"firing", "escalation", "resolving"}


async def require_service_if_auth_enabled(
    context=Depends(require_auth_if_enabled),
):
    if context is None:
        return context
    if context is None or getattr(context, "role", None) != "service":
        raise HTTPException(status_code=403, detail="Service access required")
    return context


def _recipe_has_phase_remediation(recipe: Recipe, *, phase: str) -> bool:
    for item in recipe.recipe_ingredients or []:
        ingredient = item.ingredient
        if ingredient is None:
            continue
        run_phase = str(item.run_phase or "both").strip().lower()
        if phase == "firing" and run_phase not in {"firing", "both"}:
            continue
        if phase != "firing" and run_phase != phase:
            continue
        if str(ingredient.execution_purpose or "").strip().lower() == "remediation":
            return True
    return False


def _inactive_ingredients(recipe: Recipe) -> list[tuple[int, str]]:
    inactive: list[tuple[int, str]] = []
    for item in recipe.recipe_ingredients or []:
        ingredient = item.ingredient
        if ingredient is None or bool(getattr(ingredient, "is_active", True)):
            continue
        inactive.append(
            (
                int(item.ingredient_id),
                str(
                    getattr(ingredient, "task_key_template", "")
                    or f"ingredient-{item.ingredient_id}"
                ),
            )
        )
    return sorted(set(inactive))


@router.get("/orders", response_model=List[OrderResponse])
async def fetch_orders(
    request: Request,
    params: OrderQueryParams = Depends(validate_query_params(OrderQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Get orders with optional filtering.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/waiting_clear/escalation/resolving/waiting_ticket_close/complete/failed/canceled)
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

    query = select(Order).options(joinedload(Order.communications))

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
    orders = result.unique().scalars().all()

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
    result = await db.execute(
        select(Order).options(joinedload(Order.communications)).where(Order.id == order.id)
    )
    order = result.unique().scalars().first() or order

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

    result = await db.execute(
        select(Order).options(joinedload(Order.communications)).where(Order.id == order_id)
    )
    order = result.unique().scalars().first()

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
        result = await db.execute(
            select(Order)
            .options(joinedload(Order.communications))
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.unique().scalars().first()
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
    result = await db.execute(
        select(Order).options(joinedload(Order.communications)).where(Order.id == order.id)
    )
    order = result.unique().scalars().first() or order

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


@router.post("/orders/{order_id}/dispatch", response_model=OrderDispatchResponse)
async def dispatch_order(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> OrderDispatchResponse:
    """Create/seed a phase-scoped dish for a dispatchable order."""
    req_id = request.state.req_id
    settings = get_settings()
    now = datetime.now(timezone.utc)

    response: OrderDispatchResponse | None = None
    async with db.begin():
        global_policy_is_configured = await global_policy_configured(db)
        result = await db.execute(
            select(Order)
            .options(joinedload(Order.communications))
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        run_phase: Literal["firing", "escalation", "resolving"]
        if order.processing_status == "new":
            run_phase = "firing"
        elif order.processing_status == "escalation":
            run_phase = "escalation"
        elif order.processing_status == "resolving":
            run_phase = "resolving"
        elif order.processing_status == "waiting_clear":
            if order.alert_status == "resolved":
                order.processing_status = "resolving"
                run_phase = "resolving"
            elif (
                order.clear_deadline_at
                and order.clear_timed_out_at is None
                and order.clear_deadline_at <= now
            ):
                order.clear_timed_out_at = now
                order.auto_close_eligible = False
                order.processing_status = "escalation"
                run_phase = "escalation"
            else:
                response = OrderDispatchResponse(
                    status="skipped",
                    order_id=order.id,
                    reason="Order is waiting for clear and not eligible for escalation",
                )
                order.updated_at = now
                return response
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Order is not dispatchable (status={order.processing_status})",
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
            if catch_all_name and (
                run_phase == "firing" or (order.remediation_outcome or "").lower() == "none"
            ):
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

        extra_policy_steps: list[RecipeIngredient] = []
        if recipe:
            local_routes = get_recipe_local_routes(recipe)
            has_local_policy = policy_has_enabled_routes(local_routes)
            if not has_local_policy and not global_policy_is_configured:
                recipe = None
            elif run_phase in GLOBAL_COMMS_INHERIT_PHASES and not has_local_policy:
                global_policy_recipe = await get_global_policy_recipe_for_dispatch(db)
                extra_policy_steps = (
                    list(global_policy_recipe.recipe_ingredients) if global_policy_recipe else []
                )

        if not recipe:
            if run_phase == "firing":
                order.processing_status = "waiting_clear"
                order.remediation_outcome = "none"
                order.clear_timeout_sec = None
                order.clear_deadline_at = None
                order.clear_timed_out_at = None
                order.auto_close_eligible = False
                order.is_active = True
            else:
                order.processing_status = "waiting_clear"
                order.is_active = True
            order.updated_at = now
            response = OrderDispatchResponse(
                status="skipped",
                order_id=order.id,
                reason=f"No recipe for {order.alert_group_name}",
            )
        else:
            inactive_ingredients = _inactive_ingredients(recipe)
            if inactive_ingredients:
                inactive_labels = ", ".join(
                    f"{ingredient_id}:{task_name}"
                    for ingredient_id, task_name in inactive_ingredients
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Recipe references inactive ingredients and cannot execute until updated: "
                        f"{inactive_labels}"
                    ),
                )
            if run_phase == "firing":
                order.processing_status = "processing"
                if _recipe_has_phase_remediation(recipe, phase="firing"):
                    order.remediation_outcome = "pending"
                    order.clear_timeout_sec = recipe.clear_timeout_sec
                    order.clear_deadline_at = None
                    order.clear_timed_out_at = None
                    order.auto_close_eligible = False
                else:
                    order.remediation_outcome = "none"
                    order.clear_timeout_sec = None
                    order.auto_close_eligible = False
                    order.clear_deadline_at = None
                    order.clear_timed_out_at = None
                order.updated_at = now

            dish_result = await db.execute(
                select(Dish)
                .where(
                    Dish.order_id == order.id,
                    Dish.run_phase == run_phase,
                    Dish.processing_status.in_(("new", "processing", "finalizing")),
                )
                .order_by(Dish.created_at.desc())
                .with_for_update()
            )
            dish = dish_result.scalars().first()
            if dish is None:
                expected_duration_sec = await expected_duration_for_phase(
                    db,
                    recipe_id=recipe.id,
                    phase=run_phase,
                    extra_recipe_ingredients=extra_policy_steps,
                )
                dish = Dish(
                    req_id=order.req_id,
                    order_id=order.id,
                    recipe_id=recipe.id,
                    run_phase=run_phase,
                    processing_status="new",
                    expected_duration_sec=expected_duration_sec,
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

            seeded_rows = seed_dish_ingredients_for_phase(
                dish_id=dish.id,
                recipe=recipe,
                phase=run_phase,
                order=order,
                existing_by_recipe_ingredient_id=existing_by_recipe_ingredient_id,
                extra_recipe_ingredients=extra_policy_steps,
            )
            for row in seeded_rows:
                db.add(row)
                if row.recipe_ingredient_id is not None:
                    existing_by_recipe_ingredient_id[row.recipe_ingredient_id] = row

            response = OrderDispatchResponse(
                status="dispatched",
                order_id=order.id,
                dish_id=dish.id,
                run_phase=run_phase,
                recipe_id=recipe.id,
                recipe_name=recipe.name,
            )

    if response is None:
        raise HTTPException(status_code=500, detail="Dispatch failed")
    return response


@router.get("/orders/{order_id}/timeline", response_model=IncidentTimelineResponse)
async def get_order_timeline(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> IncidentTimelineResponse:
    req_id = request.state.req_id
    result = await db.execute(
        select(Order).options(joinedload(Order.communications)).where(Order.id == order_id)
    )
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

    for communication in order.communications:
        bakery_status = communication.lifecycle_state or "unknown"
        bakery_details: dict = {
            "execution_target": communication.execution_target,
            "destination_target": communication.destination_target,
            "remote_state": communication.remote_state,
            "writable": communication.writable,
            "reopenable": communication.reopenable,
            "last_error": communication.last_error,
        }
        if communication.bakery_operation_id:
            try:
                op_payload = await get_operation(communication.bakery_operation_id)
                bakery_status = op_payload.status or bakery_status
                bakery_details["operation"] = op_payload.model_dump(mode="json")
            except Exception:
                bakery_status = communication.lifecycle_state or "unavailable"
        events.append(
            IncidentTimelineEvent(
                timestamp=communication.updated_at,
                event_type="bakery",
                status=bakery_status,
                title=(
                    f"Communication route {communication.execution_target}"
                    f":{communication.destination_target or '-'}"
                ),
                details=bakery_details,
                correlation_ids={
                    "bakery_ticket_id": communication.bakery_ticket_id or "",
                    "bakery_operation_id": communication.bakery_operation_id or "",
                    "execution_target": communication.execution_target,
                    "destination_target": communication.destination_target or "",
                    "remote_state": communication.remote_state or "",
                },
            )
        )

    if (order.bakery_ticket_id or order.bakery_operation_id) and not order.communications:
        bakery_status = "unknown"
        bakery_details = {}
        if order.bakery_operation_id:
            try:
                op_payload = await get_operation(order.bakery_operation_id)
                bakery_status = op_payload.status or "unknown"
                bakery_details = op_payload.model_dump(mode="json")
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


@router.post("/orders/{order_id}/reconcile", response_model=dict[str, Any])
async def reconcile_order_route(
    request: Request,
    order_id: int,
    _service=Depends(require_service_if_auth_enabled),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reconcile one active order against live alert and ticket state."""
    result = await reconcile_order(db, order_id=order_id, req_id=request.state.req_id)
    await db.commit()
    return result

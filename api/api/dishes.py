#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Dish (execution) management."""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update, func, asc, desc, and_, or_, case
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List, cast
from datetime import datetime, timezone, timedelta

from api.core.database import get_db
from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.statuses import DISH_TERMINAL_PROCESSING_STATUSES, ORDER_TERMINAL_PROCESSING_STATUSES
from api.models.models import Order, Dish, Recipe, RecipeIngredient, DishIngredient, Ingredient
from api.services.bakery_client import (
    add_ticket_comment,
    create_ticket,
    poll_operation,
    update_ticket,
)
from api.schemas.schemas import (
    DishResponse,
    DishUpdate,
    CookResponse,
    DishDetailResponse,
    DishIngredientBulkUpsert,
    DishIngredientResponse,
)
from api.schemas.query_params import DishQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)
TERMINAL_TICKET_STATES = {"closed", "terminal"}


def _resolved_ticket_state() -> str:
    settings = get_settings()
    if settings.bakery_active_provider.lower() == "rackspace_core":
        return (
            (settings.bakery_rackspace_confirmed_solved_status or "confirmed solved")
            .lower()
            .replace(" ", "_")
        )
    return "closed"


def _reopen_payload() -> dict[str, Any]:
    settings = get_settings()
    if settings.bakery_active_provider.lower() == "rackspace_core":
        return {"context": {"attributes": {"status": "New"}}}
    return {"state": "open"}


def _build_execution_summary(dish: Dish, ingredients: list[DishIngredient]) -> str:
    payload: dict[str, Any] = {
        "dish_id": dish.id,
        "dish_processing_status": dish.processing_status,
        "dish_status": dish.status,
        "workflow_execution_id": dish.workflow_execution_id,
        "error_message": dish.error_message,
        "result": dish.result,
        "ingredients": [],
    }
    for item in ingredients:
        payload["ingredients"].append(
            {
                "id": item.id,
                "task_id": item.task_id,
                "st2_execution_id": item.st2_execution_id,
                "status": item.status,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "error_message": item.error_message,
                "result": item.result,
            }
        )
    return json.dumps(payload, ensure_ascii=True, default=str)


async def _poll_and_apply_operation(
    *,
    req_id: str,
    order: Order,
    operation_id: str | None,
    success_state: str,
) -> None:
    if not operation_id:
        return
    try:
        op_payload = await poll_operation(operation_id)
    except TimeoutError:
        logger.info(
            "Bakery operation still in progress",
            extra={"req_id": req_id, "order_id": order.id, "operation_id": operation_id},
        )
        return

    status = str(op_payload.get("status") or "")
    if status == "dead_letter":
        order.bakery_ticket_state = "dead_letter"
        order.bakery_permanent_failure = True
        order.bakery_last_error = str(op_payload.get("last_error") or "dead_letter")
        return
    if status == "succeeded":
        order.bakery_ticket_state = success_state
        order.bakery_permanent_failure = False
        order.bakery_last_error = None


async def _ensure_order_ticket(
    *,
    req_id: str,
    order: Order,
    dish: Dish,
    execution_summary: str,
) -> None:
    existing_state = (order.bakery_ticket_state or "").lower()
    if order.bakery_ticket_id and existing_state in TERMINAL_TICKET_STATES:
        order.bakery_ticket_id = None
        order.bakery_operation_id = None
        order.bakery_ticket_state = None

    if order.bakery_ticket_id and existing_state == "confirmed_solved":
        accepted = await update_ticket(
            req_id=req_id,
            ticket_id=order.bakery_ticket_id,
            payload=_reopen_payload(),
        )
        order.bakery_operation_id = accepted.get("operation_id")
        await _poll_and_apply_operation(
            req_id=req_id,
            order=order,
            operation_id=order.bakery_operation_id,
            success_state="open",
        )
        await add_ticket_comment(
            req_id=req_id,
            ticket_id=order.bakery_ticket_id,
            comment=f"Alert re-fired for fingerprint {order.fingerprint}; reopening incident thread.",
        )

    if order.bakery_ticket_id:
        return

    create_payload = {
        "title": f"[{order.severity or 'unknown'}] {order.alert_group_name}",
        "description": (
            f"Order {order.id} completed remediation processing for req_id={order.req_id}\n"
            f"Dish {dish.id} status={dish.status or dish.processing_status}\n"
            "Execution output:\n"
            f"{execution_summary}"
        ),
        "severity": order.severity or "unknown",
        "source": "poundcake",
        "context": {
            "labels": order.labels or {},
            "annotations": order.annotations or {},
            "req_id": order.req_id,
        },
    }
    accepted = await create_ticket(req_id=req_id, payload=create_payload)
    order.bakery_ticket_id = accepted.get("ticket_id")
    order.bakery_operation_id = accepted.get("operation_id")
    await _poll_and_apply_operation(
        req_id=req_id,
        order=order,
        operation_id=order.bakery_operation_id,
        success_state="open",
    )


async def _sync_bakery_for_terminal_dish(req_id: str, dish_id: int, db: AsyncSession) -> None:
    """Synchronize Bakery tickets for terminal dish states."""
    settings = get_settings()
    if not settings.bakery_enabled:
        return

    result = await db.execute(
        select(Dish).options(joinedload(Dish.recipe)).where(Dish.id == dish_id)
    )
    dish = result.scalars().first()
    if not dish or not dish.order_id or dish.processing_status not in {"failed", "complete"}:
        return

    result = await db.execute(select(Order).where(Order.id == dish.order_id).with_for_update())
    order = result.scalars().first()
    if not order:
        return
    if order.bakery_permanent_failure:
        return

    ingredient_result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.dish_id == dish.id, DishIngredient.deleted.is_(False))
        .order_by(DishIngredient.created_at.asc())
    )
    ingredients = ingredient_result.scalars().all()
    execution_summary = _build_execution_summary(dish, ingredients)

    try:
        await _ensure_order_ticket(
            req_id=req_id,
            order=order,
            dish=dish,
            execution_summary=execution_summary,
        )
        if order.bakery_permanent_failure or not order.bakery_ticket_id:
            await db.commit()
            return

        await add_ticket_comment(
            req_id=req_id,
            ticket_id=order.bakery_ticket_id,
            comment=(
                f"Order {order.id} remediation terminal status: {dish.processing_status}\n"
                f"Execution payload:\n{execution_summary}"
            ),
        )

        if order.bakery_ticket_state is None:
            order.bakery_ticket_state = "open"
            order.bakery_permanent_failure = False
            order.bakery_last_error = None

        await db.commit()
    except Exception as exc:  # noqa: BLE001
        order.bakery_last_error = str(exc)
        await db.commit()
        logger.error(
            "Failed Bakery synchronization",
            extra={"req_id": req_id, "dish_id": dish_id, "error": str(exc)},
        )


def _rowcount(result: object) -> int:
    """Get affected row count from SQLAlchemy DML result."""
    return int(getattr(cast(Any, result), "rowcount", 0) or 0)


@router.post("/dishes/cook/{order_id}", response_model=CookResponse)
async def cook_dishes(
    request: Request, order_id: int, db: AsyncSession = Depends(get_db)
) -> CookResponse:
    """Creates a Dish execution from an Order/Recipe."""
    req_id = request.state.req_id
    settings = get_settings()

    logger.info("Starting cook", extra={"req_id": req_id, "order_id": order_id})

    new_dish: Dish | None = None
    async with db.begin():
        result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
        order = result.scalars().first()
        if not order:
            logger.warning("Order not found", extra={"req_id": req_id, "order_id": order_id})
            raise HTTPException(status_code=404, detail="Order not found")

        result = await db.execute(
            select(Recipe)
            .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
            .where(Recipe.name == order.alert_group_name, Recipe.enabled.is_(True))
            .with_for_update()
        )
        recipe = result.unique().scalars().first()
        used_fallback = False

        if not recipe:
            catch_all_name = (settings.catch_all_recipe_name or "").strip()
            if catch_all_name:
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
                used_fallback = recipe is not None

        if not recipe:
            if order.processing_status not in ORDER_TERMINAL_PROCESSING_STATUSES:
                # Keep order active until Alertmanager sends a resolved event.
                order.processing_status = "processing"
                order.is_active = True
                order.updated_at = datetime.now(timezone.utc)
            logger.error(
                "No recipe found; order remains active pending alert resolution",
                extra={
                    "req_id": req_id,
                    "order_id": order_id,
                    "group_name": order.alert_group_name,
                },
            )
            return CookResponse(status="ignored", reason=f"No recipe for {order.alert_group_name}")

        result = await db.execute(
            select(Dish).where(Dish.order_id == order.id).order_by(Dish.created_at.desc())
        )
        existing_dish = result.scalars().first()

        now = datetime.now(timezone.utc)
        update_result = await db.execute(
            update(Order)
            .where(Order.id == order.id, Order.processing_status == "new")
            .values(processing_status="processing", updated_at=now)
        )

        if _rowcount(update_result) == 0:
            reason = f"Order not new (status={order.processing_status})"
            if existing_dish:
                reason = "Order already has a dish or is being processed"
            return CookResponse(
                status="skipped",
                dishes_created=0,
                recipe_id=recipe.id,
                recipe_name=recipe.name,
                reason=reason,
            )

        expected_result = await db.execute(
            select(func.coalesce(func.sum(Ingredient.expected_duration_sec), 0))
            .select_from(RecipeIngredient)
            .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(RecipeIngredient.recipe_id == recipe.id)
        )
        expected_duration_sec = expected_result.scalar() or 0

        new_dish = Dish(
            req_id=order.req_id,
            order_id=order.id,
            recipe_id=recipe.id,
            processing_status="new",
            expected_duration_sec=expected_duration_sec,
        )
        db.add(new_dish)
        await db.flush()
        # Refresh inside transaction for consistency
        await db.refresh(new_dish)

    if not new_dish:
        raise HTTPException(status_code=500, detail="Dish creation failed")

    logger.info(
        "Dish created successfully",
        extra={
            "req_id": req_id,
            "order_id": order_id,
            "recipe_id": recipe.id,
            "dish_id": new_dish.id,
        },
    )

    return CookResponse(
        status="cooked",
        dishes_created=1,
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        reason=(
            f"Fallback recipe '{recipe.name}' selected for unmatched group {order.alert_group_name}"
            if used_fallback
            else None
        ),
    )


@router.get("/dishes", response_model=List[DishDetailResponse])
async def fetch_dishes(
    request: Request,
    params: DishQueryParams = Depends(validate_query_params(DishQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/complete/failed)
    - req_id: Filter by request ID
    - order_id: Filter by order ID (integer)
    - workflow_execution_id: Filter by StackStorm workflow execution ID
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "Fetching dishes",
        extra={
            "req_id": request_id,
            "processing_status": params.processing_status,
            "filter_req_id": params.req_id,
            "order_id": params.order_id,
            "workflow_execution_id": params.workflow_execution_id,
            "limit": params.limit,
            "offset": params.offset,
        },
    )

    query = select(Dish).options(
        joinedload(Dish.recipe)
        .joinedload(Recipe.recipe_ingredients)
        .joinedload(RecipeIngredient.ingredient)
    )

    if params.processing_status:
        query = query.where(Dish.processing_status == params.processing_status)
    if params.req_id:
        query = query.where(Dish.req_id == params.req_id)
    if params.order_id:
        query = query.where(Dish.order_id == params.order_id)
    if params.workflow_execution_id:
        query = query.where(Dish.workflow_execution_id == params.workflow_execution_id)

    if params.processing_status and params.processing_status == "new":
        query = query.order_by(asc(Dish.created_at))
    elif params.processing_status and params.processing_status == "processing":
        # MariaDB doesn't support NULLS FIRST, use CASE to sort NULL values first
        query = query.order_by(
            case((Dish.started_at.is_(None), 0), else_=1),
            asc(Dish.started_at),
            asc(Dish.created_at),
        )
    else:
        query = query.order_by(desc(Dish.created_at))

    query = query.limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    dishes = result.unique().scalars().all()

    logger.debug("Dishes fetched", extra={"req_id": request_id, "count": len(dishes)})

    return dishes


@router.post("/dishes/{dish_id}/claim", response_model=DishDetailResponse)
async def claim_dish(
    request: Request, dish_id: int, db: AsyncSession = Depends(get_db)
) -> DishDetailResponse:
    """Atomically claim a new dish for processing."""
    req_id = request.state.req_id
    now = datetime.now(timezone.utc)

    dish: Dish | None = None
    async with db.begin():
        update_result = await db.execute(
            update(Dish)
            .where(Dish.id == dish_id, Dish.processing_status == "new")
            .values(processing_status="processing", started_at=now)
        )

        if _rowcount(update_result) == 0:
            logger.info(
                "Dish claim failed",
                extra={"req_id": req_id, "dish_id": dish_id},
            )
            raise HTTPException(status_code=409, detail="Dish already claimed")

        # Fetch inside transaction for consistency
        result = await db.execute(
            select(Dish)
            .options(
                joinedload(Dish.recipe)
                .joinedload(Recipe.recipe_ingredients)
                .joinedload(RecipeIngredient.ingredient)
            )
            .where(Dish.id == dish_id)
        )
        dish = result.unique().scalars().first()

    if not dish:
        raise HTTPException(status_code=404, detail="Dish not found")
    return dish


@router.post("/dishes/{dish_id}/finalize-claim", response_model=DishDetailResponse)
async def claim_dish_for_finalize(
    request: Request, dish_id: int, db: AsyncSession = Depends(get_db)
) -> DishDetailResponse:
    """Atomically claim a processing dish for finalization."""
    req_id = request.state.req_id
    now = datetime.now(timezone.utc)
    settings = get_settings()
    stale_cutoff = now - timedelta(seconds=settings.lock_timeout_seconds)

    dish: Dish | None = None
    async with db.begin():
        update_result = await db.execute(
            update(Dish)
            .where(
                Dish.id == dish_id,
                or_(
                    Dish.processing_status == "processing",
                    and_(
                        Dish.processing_status == "finalizing",
                        Dish.updated_at < stale_cutoff,
                    ),
                ),
            )
            .values(processing_status="finalizing", updated_at=now)
        )

        if _rowcount(update_result) == 0:
            logger.info(
                "Dish finalize claim failed",
                extra={"req_id": req_id, "dish_id": dish_id},
            )
            raise HTTPException(status_code=409, detail="Dish already claimed")

        # Fetch inside transaction for consistency
        result = await db.execute(
            select(Dish)
            .options(
                joinedload(Dish.recipe)
                .joinedload(Recipe.recipe_ingredients)
                .joinedload(RecipeIngredient.ingredient)
            )
            .where(Dish.id == dish_id)
        )
        dish = result.unique().scalars().first()

    if not dish:
        raise HTTPException(status_code=404, detail="Dish not found")
    return dish


@router.post("/dishes/{dish_id}/ingredients/bulk")
async def upsert_dish_ingredients(
    request: Request,
    dish_id: int,
    payload: DishIngredientBulkUpsert,
    db: AsyncSession = Depends(get_db),
):
    """Upsert dish ingredient executions for a dish."""
    req_id = request.state.req_id

    updated = 0
    created = 0
    async with db.begin():
        result = await db.execute(
            select(Dish)
            .options(
                joinedload(Dish.recipe)
                .joinedload(Recipe.recipe_ingredients)
                .joinedload(RecipeIngredient.ingredient)
            )
            .where(Dish.id == dish_id)
            .with_for_update()
        )
        dish = result.unique().scalars().first()
        if not dish:
            raise HTTPException(status_code=404, detail="Dish not found")

        task_to_recipe_ingredient = {}
        if dish.recipe and dish.recipe.recipe_ingredients:
            for ri in dish.recipe.recipe_ingredients:
                if ri.ingredient and ri.ingredient.task_name:
                    raw_task_name = ri.ingredient.task_name
                    workflow_task_name = f"step_{ri.step_order}_{raw_task_name.replace('.', '_')}"
                    task_to_recipe_ingredient[workflow_task_name] = ri.id
                    # Keep raw task name mapping for backward compatibility.
                    task_to_recipe_ingredient[raw_task_name] = ri.id

        now = datetime.now(timezone.utc)

        seen_keys: set[tuple[str, str]] = set()
        rows: list[dict] = []
        for item in payload.items:
            task_id = item.task_id
            st2_execution_id = item.st2_execution_id
            if not task_id and not st2_execution_id:
                continue
            dedupe_key = (task_id or "", st2_execution_id or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            row = {
                "dish_id": dish_id,
                "task_id": task_id,
                "st2_execution_id": st2_execution_id,
                "status": item.status,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
                "canceled_at": item.canceled_at,
                "result": item.result,
                "error_message": item.error_message,
                "updated_at": now,
            }
            if task_id in task_to_recipe_ingredient:
                row["recipe_ingredient_id"] = task_to_recipe_ingredient[task_id]
            rows.append(row)

        if rows:
            insert_stmt = mysql_insert(DishIngredient).values(rows)
            update_stmt = {
                "task_id": insert_stmt.inserted.task_id,
                "st2_execution_id": insert_stmt.inserted.st2_execution_id,
                "status": insert_stmt.inserted.status,
                "started_at": insert_stmt.inserted.started_at,
                "completed_at": insert_stmt.inserted.completed_at,
                "canceled_at": insert_stmt.inserted.canceled_at,
                "result": insert_stmt.inserted.result,
                "error_message": insert_stmt.inserted.error_message,
                "updated_at": insert_stmt.inserted.updated_at,
                "recipe_ingredient_id": func.coalesce(
                    DishIngredient.recipe_ingredient_id,
                    insert_stmt.inserted.recipe_ingredient_id,
                ),
            }
            result = await db.execute(insert_stmt.on_duplicate_key_update(**update_stmt))
            affected_rows = _rowcount(result)
            if affected_rows >= 0:
                total_rows = len(rows)
                if affected_rows >= total_rows:
                    updated = affected_rows - total_rows
                    created = total_rows - updated
                else:
                    created = affected_rows
                    updated = 0
    logger.debug(
        "Dish ingredients upserted",
        extra={
            "req_id": req_id,
            "dish_id": dish_id,
            "created_count": created,
            "updated_count": updated,
        },
    )
    return {"created": created, "updated": updated}


@router.get("/dishes/{dish_id}/ingredients", response_model=List[DishIngredientResponse])
async def list_dish_ingredients(
    request: Request,
    dish_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List dish ingredient executions for a dish."""
    req_id = request.state.req_id

    result = await db.execute(select(Dish).where(Dish.id == dish_id))
    dish = result.scalars().first()
    if not dish:
        raise HTTPException(status_code=404, detail="Dish not found")

    result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.dish_id == dish_id, DishIngredient.deleted.is_(False))
        .order_by(
            DishIngredient.started_at.is_(None),
            DishIngredient.started_at.asc(),
            DishIngredient.completed_at.asc(),
            DishIngredient.created_at.asc(),
            DishIngredient.id.asc(),
        )
    )
    records = result.scalars().all()
    logger.debug(
        "Dish ingredients fetched",
        extra={"req_id": req_id, "dish_id": dish_id, "count": len(records)},
    )
    return records


@router.put("/dishes/{dish_id}", response_model=DishResponse)
@router.patch("/dishes/{dish_id}", response_model=DishResponse)
async def update_dish(
    request: Request, dish_id: int, payload: DishUpdate, db: AsyncSession = Depends(get_db)
):
    """Updates dish status and execution info from chef/timer."""
    req_id = request.state.req_id
    settings = get_settings()

    logger.info("Updating dish", extra={"req_id": req_id, "dish_id": dish_id})

    dish: Dish | None = None
    previous_processing_status: str | None = None
    async with db.begin():
        result = await db.execute(
            select(Dish)
            .options(joinedload(Dish.recipe))
            .where(Dish.id == dish_id)
            .with_for_update()
        )
        dish = result.unique().scalars().first()
        if not dish:
            logger.warning("Dish not found", extra={"req_id": req_id, "dish_id": dish_id})
            raise HTTPException(status_code=404, detail="Dish not found")
        previous_processing_status = dish.processing_status

        update_data = payload.model_dump(exclude_unset=True)
        if (
            dish.processing_status in DISH_TERMINAL_PROCESSING_STATUSES
            and "processing_status" in update_data
            and update_data["processing_status"] in DISH_TERMINAL_PROCESSING_STATUSES
            and update_data["processing_status"] != dish.processing_status
        ):
            logger.info(
                "Ignoring terminal status overwrite",
                extra={
                    "req_id": req_id,
                    "dish_id": dish_id,
                    "current_status": dish.processing_status,
                    "requested_status": update_data["processing_status"],
                },
            )
            return dish
        for key, value in update_data.items():
            setattr(dish, key, value)

        dish.updated_at = datetime.now(timezone.utc)

        if dish.processing_status in DISH_TERMINAL_PROCESSING_STATUSES and dish.order_id:
            catch_all_name = (settings.catch_all_recipe_name or "").strip().lower()
            is_catch_all = bool(
                catch_all_name
                and dish.recipe
                and (dish.recipe.name or "").strip().lower() == catch_all_name
            )
            result = await db.execute(
                select(Order).where(Order.id == dish.order_id).with_for_update()
            )
            order = result.scalars().first()
            if order and order.processing_status != "complete":
                if order.processing_status == "canceled":
                    logger.info(
                        "Skipping order status update because order is canceled",
                        extra={"req_id": req_id, "order_id": order.id, "dish_id": dish.id},
                    )
                elif is_catch_all:
                    # Keep catch-all orders active so resolved alerts can close/reopen the same ticket.
                    order.updated_at = datetime.now(timezone.utc)
                    logger.info(
                        "Keeping catch-all order active after dish terminal status",
                        extra={
                            "req_id": req_id,
                            "order_id": order.id,
                            "dish_id": dish.id,
                            "dish_status": dish.processing_status,
                        },
                    )
                else:
                    # Keep order in-flight until the alert itself clears.
                    order.processing_status = "processing"
                    order.is_active = True
                    order.updated_at = datetime.now(timezone.utc)

    if dish is None:
        raise HTTPException(status_code=500, detail="Dish update failed")
    await db.refresh(dish)
    if (
        previous_processing_status not in DISH_TERMINAL_PROCESSING_STATUSES
        and dish.processing_status in DISH_TERMINAL_PROCESSING_STATUSES
    ):
        await _sync_bakery_for_terminal_dish(req_id=req_id, dish_id=dish.id, db=db)

    logger.info(
        "Dish updated successfully",
        extra={
            "req_id": req_id,
            "dish_id": dish_id,
            "new_status": dish.processing_status,
        },
    )

    return dish

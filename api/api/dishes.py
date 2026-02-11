#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Dish (execution) management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update, func, asc, desc, nullsfirst, and_, or_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone, timedelta

from api.core.database import get_db
from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.statuses import DISH_TERMINAL_PROCESSING_STATUSES, ORDER_TERMINAL_PROCESSING_STATUSES
from api.models.models import Order, Dish, Recipe, RecipeIngredient, DishIngredient, Ingredient
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


@router.post("/dishes/cook/{order_id}", response_model=CookResponse)
async def cook_dishes(
    request: Request, order_id: int, db: AsyncSession = Depends(get_db)
) -> CookResponse:
    """Creates a Dish execution from an Order/Recipe."""
    req_id = request.state.req_id

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
        recipe = result.scalars().first()

        if not recipe:
            if order.processing_status not in ORDER_TERMINAL_PROCESSING_STATUSES:
                order.processing_status = "complete"
                order.is_active = False
                order.updated_at = datetime.now(timezone.utc)
            logger.error(
                "No recipe found, order closed",
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

        if update_result.rowcount == 0:  # pyright: ignore[reportAttributeAccessIssue]
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
            "processing_status": (
                params.processing_status.value if params.processing_status else None
            ),
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
        query = query.where(Dish.processing_status == params.processing_status.value)
    if params.req_id:
        query = query.where(Dish.req_id == params.req_id)
    if params.order_id:
        query = query.where(Dish.order_id == params.order_id)
    if params.workflow_execution_id:
        query = query.where(Dish.workflow_execution_id == params.workflow_execution_id)

    if params.processing_status and params.processing_status.value == "new":
        query = query.order_by(asc(Dish.created_at))
    elif params.processing_status and params.processing_status.value == "processing":
        query = query.order_by(
            nullsfirst(asc(Dish.started_at)),
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

        if update_result.rowcount == 0:  # pyright: ignore[reportAttributeAccessIssue]
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
        dish = result.scalars().first()

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

        if update_result.rowcount == 0:  # pyright: ignore[reportAttributeAccessIssue]
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
        dish = result.scalars().first()

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
        dish = result.scalars().first()
        if not dish:
            raise HTTPException(status_code=404, detail="Dish not found")

        task_to_recipe_ingredient = {}
        if dish.recipe and dish.recipe.recipe_ingredients:
            for ri in dish.recipe.recipe_ingredients:
                if ri.ingredient and ri.ingredient.task_name:
                    task_to_recipe_ingredient[ri.ingredient.task_name] = ri.id

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
            if result.rowcount is not None and result.rowcount >= 0:
                total_rows = len(rows)
                if result.rowcount >= total_rows:
                    updated = result.rowcount - total_rows
                    created = total_rows - updated
                else:
                    created = result.rowcount
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

    logger.info("Updating dish", extra={"req_id": req_id, "dish_id": dish_id})

    dish: Dish | None = None
    async with db.begin():
        result = await db.execute(select(Dish).where(Dish.id == dish_id).with_for_update())
        dish = result.scalars().first()
        if not dish:
            logger.warning("Dish not found", extra={"req_id": req_id, "dish_id": dish_id})
            raise HTTPException(status_code=404, detail="Dish not found")

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
                else:
                    order.processing_status = dish.processing_status
                    order.is_active = False
                    order.updated_at = datetime.now(timezone.utc)

    if dish is None:
        raise HTTPException(status_code=500, detail="Dish update failed")
    await db.refresh(dish)

    logger.info(
        "Dish updated successfully",
        extra={
            "req_id": req_id,
            "dish_id": dish_id,
            "new_status": dish.processing_status,
        },
    )

    return dish

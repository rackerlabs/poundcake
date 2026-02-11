#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Dish (execution) management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.core.statuses import DISH_TERMINAL_PROCESSING_STATUSES
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

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        logger.warning("Order not found", extra={"req_id": req_id, "order_id": order_id})
        raise HTTPException(status_code=404, detail="Order not found")

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == order.alert_group_name, Recipe.enabled.is_(True))
    )
    recipe = result.scalars().first()

    if not recipe:
        order.processing_status = "complete"
        order.is_active = False
        order.updated_at = datetime.now(timezone.utc)
        await db.commit()
        logger.error(
            "No recipe found, order closed",
            extra={"req_id": req_id, "order_id": order_id, "group_name": order.alert_group_name},
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
    await db.commit()
    await db.refresh(new_dish)

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

    query = query.order_by(Dish.created_at.desc()).limit(params.limit).offset(params.offset)
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

    await db.commit()

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

    task_to_recipe_ingredient = {}
    if dish.recipe and dish.recipe.recipe_ingredients:
        for ri in dish.recipe.recipe_ingredients:
            if ri.ingredient and ri.ingredient.task_name:
                task_to_recipe_ingredient[ri.ingredient.task_name] = ri.id

    updated = 0
    created = 0
    now = datetime.now(timezone.utc)

    for item in payload.items:
        task_id = item.task_id
        st2_execution_id = item.st2_execution_id
        if not task_id and not st2_execution_id:
            continue

        record_query = select(DishIngredient).where(DishIngredient.dish_id == dish_id)
        if st2_execution_id:
            record_query = record_query.where(DishIngredient.st2_execution_id == st2_execution_id)
        else:
            record_query = record_query.where(DishIngredient.task_id == task_id)

        record_result = await db.execute(record_query)
        record = record_result.scalars().first()
        if record:
            updated += 1
        else:
            record = DishIngredient(dish_id=dish_id)
            created += 1

        if task_id:
            record.task_id = task_id
        if st2_execution_id:
            record.st2_execution_id = st2_execution_id
        if item.status is not None:
            record.status = item.status
        if item.started_at is not None:
            record.started_at = item.started_at
        if item.completed_at is not None:
            record.completed_at = item.completed_at
        if item.canceled_at is not None:
            record.canceled_at = item.canceled_at
        if item.result is not None:
            record.result = item.result
        if item.error_message is not None:
            record.error_message = item.error_message
        record.updated_at = now

        if record.recipe_ingredient_id is None and task_id in task_to_recipe_ingredient:
            record.recipe_ingredient_id = task_to_recipe_ingredient[task_id]

        db.add(record)

    await db.commit()
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

    result = await db.execute(select(Dish).where(Dish.id == dish_id))
    dish = result.scalars().first()
    if not dish:
        logger.warning("Dish not found", extra={"req_id": req_id, "dish_id": dish_id})
        raise HTTPException(status_code=404, detail="Dish not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dish, key, value)

    dish.updated_at = datetime.now(timezone.utc)

    if dish.processing_status in DISH_TERMINAL_PROCESSING_STATUSES and dish.order_id:
        result = await db.execute(select(Order).where(Order.id == dish.order_id))
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

    await db.commit()
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

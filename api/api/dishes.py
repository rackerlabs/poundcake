#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Dish (execution) management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update, func, asc, desc, and_, or_, case
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List, cast
from datetime import datetime, timezone, timedelta

from api.core.config import get_settings
from api.core.database import get_db
from api.core.logging import get_logger
from api.core.statuses import (
    DISH_TERMINAL_PROCESSING_STATUSES,
    ORDER_TERMINAL_PROCESSING_STATUSES,
)
from api.models.models import Order, Dish, Recipe, RecipeIngredient, DishIngredient
from api.schemas.schemas import (
    DishResponse,
    DishUpdate,
    DishDetailResponse,
    DishIngredientBulkUpsert,
    DishIngredientBulkUpsertResponse,
    DishIngredientResponse,
)
from api.schemas.query_params import DishQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)


async def _sync_bakery_for_terminal_dish(*_args: Any, **_kwargs: Any) -> None:
    """Deprecated compatibility shim; terminal Bakery sync is now recipe-driven."""
    return None


def _rowcount(result: object) -> int:
    """Get affected row count from SQLAlchemy DML result."""
    return int(getattr(cast(Any, result), "rowcount", 0) or 0)


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
    - execution_ref: Filter by execution reference
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
            "execution_ref": params.execution_ref,
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
    if params.execution_ref:
        query = query.where(Dish.execution_ref == params.execution_ref)

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
            .values(
                processing_status="processing",
                started_at=func.coalesce(Dish.started_at, now),
                updated_at=now,
            )
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


@router.post("/dishes/{dish_id}/ingredients/bulk", response_model=DishIngredientBulkUpsertResponse)
async def upsert_dish_ingredients(
    request: Request,
    dish_id: int,
    payload: DishIngredientBulkUpsert,
    db: AsyncSession = Depends(get_db),
) -> DishIngredientBulkUpsertResponse:
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
                if ri.ingredient and ri.ingredient.task_key_template:
                    raw_task_name = ri.ingredient.task_key_template
                    workflow_task_name = f"step_{ri.step_order}_{raw_task_name.replace('.', '_')}"
                    task_to_recipe_ingredient[workflow_task_name] = ri.id
                    task_to_recipe_ingredient[raw_task_name] = ri.id

        now = datetime.now(timezone.utc)

        seen_keys: set[tuple[int, str]] = set()
        rows: list[dict] = []
        for item in payload.items:
            task_key = item.task_key
            recipe_ingredient_id = item.recipe_ingredient_id
            if recipe_ingredient_id is None and task_key:
                recipe_ingredient_id = task_to_recipe_ingredient.get(task_key)
            execution_ref = item.execution_ref
            if recipe_ingredient_id is None and not task_key and execution_ref:
                # Keep unknown tasks stable under step-identity uniqueness.
                task_key = execution_ref
            if recipe_ingredient_id is None and not task_key:
                continue
            dedupe_key = (recipe_ingredient_id or 0, task_key or "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            row = {
                "dish_id": dish_id,
                "recipe_ingredient_id": recipe_ingredient_id,
                "task_key": task_key,
                "execution_engine": item.execution_engine,
                "execution_target": item.execution_target,
                "destination_target": item.destination_target,
                "execution_ref": execution_ref,
                "execution_payload": item.execution_payload,
                "execution_parameters": item.execution_parameters,
                "execution_status": item.execution_status,
                "attempt": item.attempt or 0,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
                "canceled_at": item.canceled_at,
                "result": item.result,
                "error_message": item.error_message,
                "updated_at": now,
            }
            rows.append(row)

        if rows:
            insert_stmt = mysql_insert(DishIngredient).values(rows)
            update_stmt = {
                "task_key": func.coalesce(DishIngredient.task_key, insert_stmt.inserted.task_key),
                "execution_engine": func.coalesce(
                    DishIngredient.execution_engine, insert_stmt.inserted.execution_engine
                ),
                "execution_target": func.coalesce(
                    DishIngredient.execution_target, insert_stmt.inserted.execution_target
                ),
                "destination_target": func.coalesce(
                    DishIngredient.destination_target, insert_stmt.inserted.destination_target
                ),
                "execution_ref": insert_stmt.inserted.execution_ref,
                "execution_payload": func.coalesce(
                    insert_stmt.inserted.execution_payload, DishIngredient.execution_payload
                ),
                "execution_parameters": func.coalesce(
                    insert_stmt.inserted.execution_parameters, DishIngredient.execution_parameters
                ),
                "execution_status": insert_stmt.inserted.execution_status,
                "attempt": insert_stmt.inserted.attempt,
                "started_at": func.coalesce(
                    DishIngredient.started_at, insert_stmt.inserted.started_at
                ),
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
    return DishIngredientBulkUpsertResponse(created=created, updated=updated)


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
            if order and order.processing_status not in ORDER_TERMINAL_PROCESSING_STATUSES:
                current_phase = (dish.run_phase or "").lower()
                now = datetime.now(timezone.utc)
                if current_phase == "resolving":
                    order.processing_status = (
                        "complete" if dish.processing_status == "complete" else "failed"
                    )
                    order.is_active = False
                elif current_phase == "escalation":
                    order.processing_status = "waiting_clear"
                    order.is_active = True
                else:
                    if (order.remediation_outcome or "").lower() == "none":
                        order.processing_status = "waiting_clear"
                        order.auto_close_eligible = False
                        order.clear_deadline_at = None
                        order.is_active = True
                    elif dish.processing_status == "complete":
                        order.remediation_outcome = "succeeded"
                        order.processing_status = "waiting_clear"
                        if order.clear_timeout_sec is None and dish.recipe is not None:
                            order.clear_timeout_sec = dish.recipe.clear_timeout_sec
                        if order.clear_timeout_sec and order.clear_deadline_at is None:
                            order.clear_deadline_at = now + timedelta(
                                seconds=int(order.clear_timeout_sec)
                            )
                        order.auto_close_eligible = True
                        order.is_active = True
                    else:
                        order.remediation_outcome = "failed"
                        order.processing_status = "escalation"
                        order.auto_close_eligible = False
                        order.clear_deadline_at = None
                        order.is_active = True
                order.updated_at = now

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

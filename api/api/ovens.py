#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Oven (task execution) management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Alert, Oven, Recipe, Ingredient
from api.schemas.schemas import OvenResponse, OvenUpdate, BakeResponse, OvenDetailResponse
from api.schemas.query_params import OvenQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)


@router.post("/ovens/bake/{alert_id}", response_model=BakeResponse)
async def bake_ovens(
    request: Request, alert_id: int, db: AsyncSession = Depends(get_db)
) -> BakeResponse:
    """Creates individual Oven tasks from a Recipe."""
    req_id = request.state.req_id

    logger.info("Starting", extra={"req_id": req_id, "alert_id": alert_id})

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalars().first()
    if not alert:
        logger.warning(
            "Alert not found", extra={"req_id": req_id, "alert_id": alert_id}
        )
        raise HTTPException(status_code=404, detail="Alert not found")

    # Match group_name to Recipe
    logger.debug(
        "Looking for recipe", extra={"req_id": req_id, "group_name": alert.group_name}
    )

    result = await db.execute(
        select(Recipe).where(Recipe.name == alert.group_name, Recipe.enabled)
    )
    recipe = result.scalars().first()

    if not recipe:
        # Close alert if no recipe exists
        alert.processing_status = "complete"
        alert.updated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.error(
            "No recipe found, alert closed",
            extra={"req_id": req_id, "alert_id": alert_id, "group_name": alert.group_name},
        )
        return BakeResponse(status="ignored", reason=f"No recipe for {alert.group_name}")

    # Fetch ingredients
    result = await db.execute(
        select(Ingredient)
        .where(Ingredient.recipe_id == recipe.id)
        .order_by(Ingredient.task_order)
    )
    ingredients = result.scalars().all()

    logger.info(
        "Recipe matched, creating ovens",
        extra={
            "req_id": req_id,
            "alert_id": alert_id,
            "recipe_id": recipe.id,
            "recipe_name": recipe.name,
            "ingredient_count": len(ingredients),
        },
    )

    for ing in ingredients:
        new_oven = Oven(
            req_id=alert.req_id,
            alert_id=alert.id,
            recipe_id=recipe.id,
            ingredient_id=ing.id,
            task_order=ing.task_order,
            processing_status="new",
            is_blocking=ing.is_blocking,
            expected_duration=ing.expected_time_to_completion,
        )
        db.add(new_oven)

    # Move alert to processing so Oven Service doesn't bake it again
    alert.processing_status = "processing"
    await db.commit()

    logger.info(
        "Ovens created successfully",
        extra={
            "req_id": req_id,
            "alert_id": alert_id,
            "recipe_id": recipe.id,
            "ovens_created": len(ingredients),
        },
    )

    return BakeResponse(
        status="baked", ovens_created=len(ingredients), recipe_id=recipe.id, recipe_name=recipe.name
    )


@router.get("/ovens", response_model=List[OvenDetailResponse])
async def list_ovens(
    request: Request,
    params: OvenQueryParams = Depends(validate_query_params(OvenQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Used by oven.py to find executable tasks and Timer to monitor status.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/complete/failed)
    - req_id: Filter by request ID
    - alert_id: Filter by alert ID (integer)
    - action_id: Filter by StackStorm action/execution ID (24-char hex string)
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "Fetching ovens",
        extra={
            "req_id": request_id,
            "processing_status": (
                params.processing_status.value if params.processing_status else None
            ),
            "filter_req_id": params.req_id,
            "alert_id": params.alert_id,
            "action_id": params.action_id,
            "limit": params.limit,
            "offset": params.offset,
        },
    )

    # Eager load ingredient relationship for oven executor
    query = select(Oven).options(selectinload(Oven.ingredient))

    if params.processing_status:
        query = query.where(Oven.processing_status == params.processing_status.value)
    if params.req_id:
        query = query.where(Oven.req_id == params.req_id)
    if params.alert_id:
        query = query.where(Oven.alert_id == params.alert_id)
    if params.action_id:
        query = query.where(Oven.action_id == params.action_id)

    query = query.order_by(Oven.created_at.desc()).limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    ovens = result.scalars().all()

    logger.debug(
        "Ovens fetched", extra={"req_id": request_id, "count": len(ovens)}
    )

    return ovens


@router.put("/ovens/{oven_id}", response_model=OvenResponse)
@router.patch("/ovens/{oven_id}", response_model=OvenResponse)
async def update_oven(
    request: Request, oven_id: int, payload: OvenUpdate, db: AsyncSession = Depends(get_db)
):
    """Updates oven status/action_id from oven.py or results from Timer."""
    req_id = request.state.req_id

    logger.info("Starting", extra={"req_id": req_id, "oven_id": oven_id})

    result = await db.execute(select(Oven).where(Oven.id == oven_id))
    oven = result.scalars().first()
    if not oven:
        logger.warning("Oven not found", extra={"req_id": req_id, "oven_id": oven_id})
        raise HTTPException(status_code=404, detail="Oven not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(oven, key, value)

    await db.commit()
    await db.refresh(oven)

    # --- Parent Alert Status Synchronization ---
    # List of terminal statuses that count as "finished"
    terminal_statuses = ["complete", "failed", "abandoned", "timeout", "canceled"]

    if oven.processing_status in terminal_statuses:
        # Check if any other ovens for this alert are still active
        result = await db.execute(
            select(func.count(Oven.id)).where(
                Oven.alert_id == oven.alert_id,
                Oven.processing_status.notin_(terminal_statuses),
                Oven.id != oven.id,
            )
        )
        remaining_active = result.scalar() or 0

        if remaining_active == 0:
            result = await db.execute(select(Alert).where(Alert.id == oven.alert_id))
            alert = result.scalars().first()
            if alert and alert.processing_status != "complete":
                logger.info(
                    "All ovens finished. Closing alert.",
                    extra={"req_id": req_id, "alert_id": alert.id},
                )
                alert.processing_status = "complete"
                alert.updated_at = datetime.now(timezone.utc)
                await db.commit()

    logger.info(
        "Oven updated successfully",
        extra={
            "req_id": req_id,
            "oven_id": oven_id,
            "new_status": oven.processing_status,
        },
    )

    return oven

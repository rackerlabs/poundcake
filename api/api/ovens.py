#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Oven (task execution) management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Alert, Oven, Recipe, Ingredient
from api.schemas.schemas import OvenResponse, OvenUpdate, BakeResponse, OvenDetailResponse
from api.validation import (
    ProcessingStatus,
    get_processing_status_param,
    get_req_id_param,
    get_alert_id_param,
    get_limit_param,
    get_offset_param,
)

router = APIRouter()
logger = get_logger(__name__)


@router.post("/ovens/bake/{alert_id}", response_model=BakeResponse)
async def bake_ovens(
    request: Request, alert_id: int, db: Session = Depends(get_db)
) -> BakeResponse:
    """Creates individual Oven tasks from a Recipe."""
    req_id = request.state.req_id

    logger.info("bake_ovens: Starting", extra={"req_id": req_id, "alert_id": alert_id})

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        logger.warning(
            "bake_ovens: Alert not found", extra={"req_id": req_id, "alert_id": alert_id}
        )
        raise HTTPException(status_code=404, detail="Alert not found")

    # Match group_name to Recipe
    logger.debug(
        "bake_ovens: Looking for recipe", extra={"req_id": req_id, "group_name": alert.group_name}
    )

    recipe = (
        db.query(Recipe).filter(Recipe.name == alert.group_name, Recipe.enabled == True).first()
    )

    if not recipe:
        # Close alert if no recipe exists
        alert.processing_status = "complete"
        db.commit()

        logger.error(
            "bake_ovens: No recipe found, alert closed",
            extra={"req_id": req_id, "alert_id": alert_id, "group_name": alert.group_name},
        )
        return BakeResponse(status="ignored", reason=f"No recipe for {alert.group_name}")

    # Fetch ingredients
    ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.recipe_id == recipe.id)
        .order_by(Ingredient.task_order)
        .all()
    )

    logger.info(
        "bake_ovens: Recipe matched, creating ovens",
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
    db.commit()

    logger.info(
        "bake_ovens: Ovens created successfully",
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
    processing_status: Optional[ProcessingStatus] = get_processing_status_param(),
    req_id: Optional[str] = get_req_id_param(),
    alert_id: Optional[int] = get_alert_id_param(),
    limit: int = get_limit_param(),
    offset: int = get_offset_param(),
    db: Session = Depends(get_db),
):
    """
    Used by oven.py to find executable tasks and Timer to monitor status.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/complete/failed)
    - req_id: Filter by request ID
    - alert_id: Filter by alert ID
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 400 Bad Request if invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "list_ovens: Fetching ovens",
        extra={
            "req_id": request_id,
            "processing_status": processing_status.value if processing_status else None,
            "filter_req_id": req_id,
            "alert_id": alert_id,
            "limit": limit,
            "offset": offset,
        },
    )

    # Eager load ingredient relationship for oven executor
    query = db.query(Oven).join(Ingredient)

    if processing_status:
        query = query.filter(Oven.processing_status == processing_status.value)
    if req_id:
        query = query.filter(Oven.req_id == req_id)
    if alert_id:
        query = query.filter(Oven.alert_id == alert_id)

    ovens = query.order_by(Oven.created_at.desc()).limit(limit).offset(offset).all()

    logger.debug("list_ovens: Ovens fetched", extra={"req_id": request_id, "count": len(ovens)})

    return ovens


@router.put("/ovens/{oven_id}", response_model=OvenResponse)
@router.patch("/ovens/{oven_id}", response_model=OvenResponse)
async def update_oven(
    request: Request, oven_id: int, payload: OvenUpdate, db: Session = Depends(get_db)
):
    """Updates oven status/action_id from oven.py or results from Timer.

    Supports both PUT and PATCH for partial updates (PATCH is more semantically correct).
    """
    req_id = request.state.req_id

    logger.info("update_oven: Starting", extra={"req_id": req_id, "oven_id": oven_id})

    oven = db.query(Oven).filter(Oven.id == oven_id).first()
    if not oven:
        logger.warning("update_oven: Oven not found", extra={"req_id": req_id, "oven_id": oven_id})
        raise HTTPException(status_code=404, detail="Oven not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(oven, key, value)

    db.commit()
    db.refresh(oven)

    logger.info(
        "update_oven: Oven updated successfully",
        extra={
            "req_id": req_id,
            "oven_id": oven_id,
            "fields_updated": len(update_data),
            "new_status": oven.processing_status,
        },
    )

    return oven

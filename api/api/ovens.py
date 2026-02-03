#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Oven (task execution) management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from api.core.database import get_db
from api.models.models import Alert, Oven, Recipe, Ingredient
from api.schemas.schemas import OvenResponse, OvenUpdate

router = APIRouter()

@router.post("/ovens/bake/{alert_id}")
async def bake_ovens(alert_id: int, db: Session = Depends(get_db)):
    """The 'Chef' logic: Creates individual Oven tasks from a Recipe."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Match group_name to Recipe
    recipe = db.query(Recipe).filter(
        Recipe.name == alert.group_name, 
        Recipe.enabled == True
    ).first()
    
    if not recipe:
        # Close alert if no recipe exists
        alert.processing_status = "complete"
        db.commit()
        return {"status": "ignored", "reason": f"No recipe for {alert.group_name}"}

    # Fetch ingredients (steps)
    ingredients = db.query(Ingredient).filter(Ingredient.recipe_id == recipe.id).all()

    for ing in ingredients:
        new_oven = Oven(
            req_id=alert.req_id,
            alert_id=alert.id,
            recipe_id=recipe.id,
            ingredient_id=ing.id,
            task_order=ing.task_order,
            processing_status="new",
            is_blocking=ing.is_blocking,
            expected_duration=ing.expected_time_to_completion
        )
        db.add(new_oven)

    # Move alert to processing so Oven Service doesn't bake it again
    alert.processing_status = "processing"
    db.commit()
    
    return {"status": "baked", "ovens_created": len(ingredients)}

@router.get("/ovens", response_model=List[OvenResponse])
async def list_ovens(
    processing_status: Optional[str] = None,
    req_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Used by oven.py to find executable tasks and Timer to monitor status."""
    query = db.query(Oven)
    if processing_status:
        query = query.filter(Oven.processing_status == processing_status)
    if req_id:
        query = query.filter(Oven.req_id == req_id)
        
    return query.all()

@router.put("/ovens/{oven_id}", response_model=OvenResponse)
@router.patch("/ovens/{oven_id}", response_model=OvenResponse)
async def update_oven(
    oven_id: int, 
    payload: OvenUpdate,  # Changed from OvenBase - allows partial updates
    db: Session = Depends(get_db)
):
    """Updates oven status/action_id from oven.py or results from Timer.
    
    Supports both PUT and PATCH for partial updates (PATCH is more semantically correct).
    """
    oven = db.query(Oven).filter(Oven.id == oven_id).first()
    if not oven:
        raise HTTPException(status_code=404, detail="Oven not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(oven, key, value)

    db.commit()
    db.refresh(oven)
    return oven

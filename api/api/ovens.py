#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for oven management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from api.core.database import get_db
from api.models.models import Oven, Ingredient, Alert

router = APIRouter()


@router.get("/api/v1/ovens")
async def get_ovens(
    processing_status: Optional[str] = None,
    req_id: Optional[str] = None,
    alert_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get ovens with optional filtering."""
    query = db.query(Oven)
    
    if processing_status:
        query = query.filter(Oven.processing_status == processing_status)
    if req_id:
        query = query.filter(Oven.req_id == req_id)
    if alert_id:
        query = query.filter(Oven.alert_id == alert_id)
    
    return query.all()


@router.get("/api/v1/ovens/{oven_id}")
async def get_oven(oven_id: int, db: Session = Depends(get_db)):
    """Get a specific oven by ID."""
    oven = db.query(Oven).filter(Oven.id == oven_id).first()
    if not oven:
        raise HTTPException(status_code=404, detail="Oven not found")
    return oven


@router.put("/api/v1/ovens/{oven_id}")
async def update_oven(oven_id: int, update_data: dict, db: Session = Depends(get_db)):
    """Update oven status and results."""
    oven = db.query(Oven).filter(Oven.id == oven_id).first()
    if not oven:
        raise HTTPException(status_code=404, detail="Oven not found")
    
    for key, value in update_data.items():
        if hasattr(oven, key):
            setattr(oven, key, value)
    
    oven.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(oven)
    return oven


@router.get("/api/v1/executions/{req_id}")
async def get_executions_by_request(req_id: str, db: Session = Depends(get_db)):
    """Get all executions (ovens) for a specific request ID."""
    return db.query(Oven).filter(Oven.req_id == req_id).all()


@router.get("/api/v1/ingredients/{ingredient_id}")
async def get_ingredient(ingredient_id: int, db: Session = Depends(get_db)):
    """Get ingredient details."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient


@router.get("/api/v1/alerts/{alert_id}")
async def get_alert(alert_id: int, db: Session = Depends(get_db)):
    """Get alert details."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.put("/api/v1/alerts/{alert_id}")
async def update_alert_status(alert_id: int, update_data: dict, db: Session = Depends(get_db)):
    """Update alert processing status."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    for key, value in update_data.items():
        if hasattr(alert, key):
            setattr(alert, key, value)
    
    alert.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    return alert

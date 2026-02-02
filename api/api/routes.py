#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Alert management."""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from api.core.database import get_db
from api.models.models import Alert
from api.schemas.schemas import AlertResponse, AlertBase
from api.services.pre_heat import pre_heat

router = APIRouter()

@router.post("/webhook")
async def alertmanager_webhook(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Entry point for Alertmanager webhooks. Handled by pre_heat service."""
    return pre_heat(payload, db)

@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    processing_status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Used by Oven Service to find 'new' alerts to bake."""
    query = db.query(Alert)
    if processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    return query.order_by(Alert.created_at.desc()).limit(limit).all()

@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert

@router.put("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int, 
    payload: AlertBase, 
    db: Session = Depends(get_db)
):
    """Used by Timer to set status to 'complete' or Oven Service to 'processing'."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)
    
    alert.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert

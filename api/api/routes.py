#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Alert management."""
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Alert
from api.schemas.schemas import AlertResponse, AlertUpdate, WebhookResponse
from api.services.pre_heat import pre_heat

router = APIRouter()
logger = get_logger(__name__)

@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def alertmanager_webhook(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db)
) -> WebhookResponse:
    """Entry point for Alertmanager webhooks. Handled by pre_heat service.
    
    Returns 202 Accepted - webhook received and queued for asynchronous processing.
    """
    req_id = request.state.req_id
    alert_count = len(payload.get("alerts", []))
    
    logger.info(
        "alertmanager_webhook: Received webhook from Alertmanager",
        extra={"req_id": req_id, "alert_count": alert_count}
    )
    
    result = pre_heat(payload, db, req_id)
    
    logger.info(
        "alertmanager_webhook: Webhook processed successfully",
        extra={"req_id": req_id, "status": result.get("status"), "alert_id": result.get("alert_id")}
    )
    
    return WebhookResponse(
        status=result["status"],
        alert_id=result.get("alert_id"),
        message=f"Alert {result['status']}"
    )

@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    request: Request,
    processing_status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Used by Oven Service to find 'new' alerts to bake."""
    req_id = request.state.req_id
    
    logger.debug(
        "get_alerts: Fetching alerts",
        extra={"req_id": req_id, "processing_status": processing_status, "limit": limit}
    )
    
    query = db.query(Alert)
    if processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    
    alerts = query.order_by(Alert.created_at.desc()).limit(limit).all()
    
    logger.debug(
        "get_alerts: Alerts fetched successfully",
        extra={"req_id": req_id, "count": len(alerts)}
    )
    
    return alerts

@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    request: Request,
    alert_id: int,
    db: Session = Depends(get_db)
):
    """Retrieve a specific alert by ID."""
    req_id = request.state.req_id
    
    logger.debug(
        "get_alert: Fetching alert by ID",
        extra={"req_id": req_id, "alert_id": alert_id}
    )
    
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    
    if not alert:
        logger.warning(
            "get_alert: Alert not found",
            extra={"req_id": req_id, "alert_id": alert_id}
        )
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return alert

@router.put("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    request: Request,
    alert_id: int, 
    payload: AlertUpdate,
    db: Session = Depends(get_db)
):
    """Used by Timer to set status to 'complete' or Oven Service to 'processing'."""
    req_id = request.state.req_id
    
    logger.info(
        "update_alert: Updating alert",
        extra={"req_id": req_id, "alert_id": alert_id}
    )
    
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        logger.warning(
            "update_alert: Alert not found for update",
            extra={"req_id": req_id, "alert_id": alert_id}
        )
        raise HTTPException(status_code=404, detail="Alert not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)
    
    alert.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    
    logger.info(
        "update_alert: Alert updated successfully",
        extra={
            "req_id": req_id,
            "alert_id": alert_id,
            "fields_updated": len(update_data),
            "new_status": alert.processing_status
        }
    )
    
    return alert

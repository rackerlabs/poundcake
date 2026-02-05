#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for Alert management."""

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Alert
from api.schemas.schemas import AlertResponse, AlertUpdate, WebhookResponse
from api.services.pre_heat import pre_heat
from api.schemas.query_params import AlertQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)


@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def alertmanager_webhook(
    request: Request, payload: dict = Body(...), db: AsyncSession = Depends(get_db)
) -> WebhookResponse:
    """Entry point for Alertmanager webhooks. Handled by pre_heat service.

    Returns 202 Accepted - webhook received and queued for asynchronous processing.
    """
    req_id = request.state.req_id
    alert_count = len(payload.get("alerts", []))

    logger.info(
        "Received webhook from Alertmanager",
        extra={"req_id": req_id, "alert_count": alert_count},
    )

    result = await pre_heat(payload, db, req_id)

    logger.info(
        "Webhook processed successfully",
        extra={
            "req_id": req_id,
            "status": result.get("status"),
            "alert_id": result.get("alert_id"),
        },
    )

    return WebhookResponse(
        status=result["status"],
        alert_id=result.get("alert_id"),
        message=f"Alert {result['status']}",
    )


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    request: Request,
    params: AlertQueryParams = Depends(validate_query_params(AlertQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    Get alerts with optional filtering.

    Query Parameters:
    - processing_status: Filter by processing status (new/pending/processing/complete/failed)
    - alert_status: Filter by alert status (firing/resolved)
    - req_id: Filter by request ID
    - alert_name: Filter by alert name
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    request_id = request.state.req_id

    logger.debug(
        "Fetching alerts",
        extra={
            "req_id": request_id,
            "processing_status": (
                params.processing_status.value if params.processing_status else None
            ),
            "alert_status": params.alert_status.value if params.alert_status else None,
            "filter_req_id": params.req_id,
            "alert_name": params.alert_name,
            "limit": params.limit,
            "offset": params.offset,
        },
    )

    query = select(Alert)

    if params.processing_status:
        query = query.where(Alert.processing_status == params.processing_status.value)
    if params.alert_status:
        query = query.where(Alert.alert_status == params.alert_status.value)
    if params.req_id:
        query = query.where(Alert.req_id == params.req_id)
    if params.alert_name:
        query = query.where(Alert.alert_name == params.alert_name)

    query = query.order_by(Alert.created_at.desc()).limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    alerts = result.scalars().all()

    logger.debug(
        "Alerts fetched successfully",
        extra={"req_id": request_id, "count": len(alerts)},
    )

    return alerts


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(request: Request, alert_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve a specific alert by ID."""
    req_id = request.state.req_id

    logger.debug("Fetching alert by ID", extra={"req_id": req_id, "alert_id": alert_id})

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalars().first()

    if not alert:
        logger.warning("Alert not found", extra={"req_id": req_id, "alert_id": alert_id})
        raise HTTPException(status_code=404, detail="Alert not found")

    return alert


@router.put("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    request: Request, alert_id: int, payload: AlertUpdate, db: AsyncSession = Depends(get_db)
):
    """Used by Timer to set status to 'complete' or Oven Service to 'processing'."""
    req_id = request.state.req_id

    logger.info("Updating alert", extra={"req_id": req_id, "alert_id": alert_id})

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalars().first()
    if not alert:
        logger.warning(
            "Alert not found for update",
            extra={"req_id": req_id, "alert_id": alert_id},
        )
        raise HTTPException(status_code=404, detail="Alert not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)

    alert.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(alert)

    logger.info(
        "Alert updated successfully",
        extra={
            "req_id": req_id,
            "alert_id": alert_id,
            "fields_updated": len(update_data),
            "new_status": alert.processing_status,
        },
    )

    return alert

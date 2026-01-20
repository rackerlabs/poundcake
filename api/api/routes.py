"""API routes for webhook and alert management."""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from celery.result import AsyncResult
from api.core.database import get_db
from api.core.middleware import get_request_id, get_api_call_id
from api.core.logging import get_logger
from api.models.models import Alert, TaskExecution
from api.schemas.schemas import (
    AlertmanagerWebhook,
    WebhookResponse,
    AlertResponse,
    TaskStatusResponse,
)
from api.tasks.tasks import celery_app
from api.tasks.alert_tasks import process_alert_batch

logger = get_logger(__name__)
router = APIRouter()


@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def receive_alertmanager_webhook(
    webhook: AlertmanagerWebhook, request: Request, db: Session = Depends(get_db)
) -> WebhookResponse:
    """
    Receive and process Alertmanager webhook.

    This endpoint:
    1. Receives alerts from Alertmanager
    2. Stores them in the database
    3. Queues them for processing via Celery
    4. Returns immediately with 202 Accepted
    """
    request_id = get_request_id(request)
    api_call_id = get_api_call_id(request)

    logger.info(
        f"Received Alertmanager webhook with {len(webhook.alerts)} alerts",
        extra={"request_id": request_id},
    )

    if not webhook.alerts:
        return WebhookResponse(
            status="no_alerts",
            request_id=request_id,
            alerts_received=0,
            task_ids=[],
            message="No alerts in webhook payload",
        )

    alert_fingerprints = []

    # Store alerts in database
    for alert_data in webhook.alerts:
        try:
            # Check if alert already exists
            existing_alert = (
                db.query(Alert).filter(Alert.fingerprint == alert_data.fingerprint).first()
            )

            if existing_alert:
                # Update existing alert
                existing_alert.status = alert_data.status
                existing_alert.ends_at = alert_data.endsAt
                existing_alert.updated_at = datetime.utcnow()
                existing_alert.raw_data = alert_data.model_dump(mode="json")
                logger.info(f"Updated existing alert: {alert_data.fingerprint}")
            else:
                # Create new alert
                alert = Alert(
                    api_call_id=api_call_id,
                    fingerprint=alert_data.fingerprint,
                    status=alert_data.status,
                    alert_name=alert_data.labels.alertname,
                    severity=alert_data.labels.severity,
                    instance=alert_data.labels.instance,
                    labels=alert_data.labels.model_dump(mode="json"),
                    annotations=(
                        alert_data.annotations.model_dump(mode="json")
                        if alert_data.annotations
                        else None
                    ),
                    starts_at=alert_data.startsAt,
                    ends_at=alert_data.endsAt,
                    generator_url=alert_data.generatorURL,
                    raw_data=alert_data.model_dump(mode="json"),
                    processing_status="pending",
                )
                db.add(alert)
                logger.info(f"Created new alert: {alert_data.fingerprint}")

            alert_fingerprints.append(alert_data.fingerprint)

        except Exception as e:
            logger.error(f"Error storing alert {alert_data.fingerprint}: {e}", exc_info=True)
            # Continue processing other alerts
            continue

    # Commit all alerts
    db.commit()

    # Queue alerts for processing
    task_ids = []
    if alert_fingerprints:
        try:
            result = process_alert_batch.delay(alert_fingerprints, request_id)
            task_ids.append(result.id)

            # Record batch task execution
            task_execution = TaskExecution(
                task_id=result.id,
                task_name="process_alert_batch",
                status="pending",
                args=[],
                kwargs={"fingerprints": alert_fingerprints, "request_id": request_id},
            )
            db.add(task_execution)
            db.commit()

            logger.info(
                f"Queued {len(alert_fingerprints)} alerts for processing",
                extra={"request_id": request_id, "task_id": result.id},
            )

        except Exception as e:
            logger.error(f"Error queuing alerts for processing: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to queue alerts for processing")

    return WebhookResponse(
        status="accepted",
        request_id=request_id,
        alerts_received=len(webhook.alerts),
        task_ids=task_ids,
        message=f"Successfully received and queued {len(webhook.alerts)} alerts",
    )


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by alert status (firing/resolved)"),
    processing_status: Optional[str] = Query(None, description="Filter by processing status"),
    alert_name: Optional[str] = Query(None, description="Filter by alert name"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(100, le=1000, description="Maximum number of alerts to return"),
    offset: int = Query(0, ge=0, description="Number of alerts to skip"),
    db: Session = Depends(get_db),
) -> List[AlertResponse]:
    """List alerts with optional filtering."""

    query = db.query(Alert)

    # Apply filters
    if status:
        query = query.filter(Alert.status == status)
    if processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    if alert_name:
        query = query.filter(Alert.alert_name == alert_name)
    if severity:
        query = query.filter(Alert.severity == severity)

    # Order by created_at descending
    query = query.order_by(desc(Alert.created_at))

    # Apply pagination
    alerts = query.offset(offset).limit(limit).all()

    return alerts


@router.get("/alerts/{fingerprint}", response_model=AlertResponse)
def get_alert(fingerprint: str, db: Session = Depends(get_db)) -> AlertResponse:
    """Get a specific alert by fingerprint."""

    alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return alert


@router.post("/alerts/{fingerprint}/retry")
async def retry_alert(
    fingerprint: str, request: Request, db: Session = Depends(get_db)
) -> WebhookResponse:
    """Retry processing for a specific alert."""

    request_id = get_request_id(request)

    alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.processing_status not in ["failed", "completed"]:
        raise HTTPException(
            status_code=400, detail=f"Cannot retry alert in {alert.processing_status} status"
        )

    # Reset processing status
    alert.processing_status = "pending"
    alert.error_message = None
    db.commit()

    # Queue for processing
    from api.tasks.tasks import process_alert

    result = process_alert.delay(alert.id, request_id)

    # Record task execution
    task_execution = TaskExecution(
        task_id=result.id,
        task_name="process_alert",
        alert_fingerprint=fingerprint,
        status="pending",
        args=[],
        kwargs={"alert_id": alert.id, "request_id": request_id},
    )
    db.add(task_execution)
    db.commit()

    logger.info(f"Queued alert for retry: {fingerprint}", extra={"request_id": request_id})

    return WebhookResponse(
        status="queued",
        request_id=request_id,
        alerts_received=1,
        task_ids=[result.id],
        message=f"Alert {fingerprint} queued for retry",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)) -> TaskStatusResponse:
    """Get the status of a Celery task."""

    # Try to get from database first
    task_execution = db.query(TaskExecution).filter(TaskExecution.task_id == task_id).first()

    if task_execution:
        return TaskStatusResponse(
            task_id=task_id,
            status=task_execution.status,
            result=task_execution.result,
            error=task_execution.error,
        )

    # Fall back to Celery result backend
    result = AsyncResult(task_id, app=celery_app)

    return TaskStatusResponse(
        task_id=task_id,
        status=result.status,
        result=result.result if result.ready() and result.successful() else None,
        error=str(result.info) if result.ready() and not result.successful() else None,
    )

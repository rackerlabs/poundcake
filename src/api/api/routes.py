"""API routes for webhook and alert management."""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from celery.result import AsyncResult
from api.core.database import get_db
from api.core.middleware import get_request_id, get_api_call_id
from api.core.logging import get_logger
from api.models.models import Alert, APICall, ST2ExecutionLink, TaskResult
from api.schemas.schemas import (
    AlertmanagerWebhook,
    WebhookResponse,
    AlertResponse,
    TaskStatusResponse,
)
from api.tasks.tasks import celery_app, process_alert

logger = get_logger(__name__)
router = APIRouter()


@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def receive_alertmanager_webhook(
    webhook: AlertmanagerWebhook,
    request: Request,
    db: Session = Depends(get_db)
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
        extra={"request_id": request_id}
    )
    
    if not webhook.alerts:
        return WebhookResponse(
            status="no_alerts",
            request_id=request_id,
            alerts_received=0,
            task_ids=[],
            message="No alerts in webhook payload"
        )
    
    alert_ids = []
    
    # Store alerts in database
    for alert_data in webhook.alerts:
        try:
            # Check if alert already exists
            existing_alert = db.query(Alert).filter(
                Alert.fingerprint == alert_data.fingerprint
            ).first()
            
            if existing_alert:
                # Update existing alert
                existing_alert.status = alert_data.status
                existing_alert.ends_at = alert_data.endsAt
                existing_alert.updated_at = datetime.utcnow()
                existing_alert.raw_data = alert_data.model_dump(mode='json')
                logger.info(f"Updated existing alert: {alert_data.fingerprint}")
                alert_ids.append(existing_alert.id)
            else:
                # Create new alert
                alert = Alert(
                    api_call_id=api_call_id,
                    fingerprint=alert_data.fingerprint,
                    status=alert_data.status,
                    alert_name=alert_data.labels.alertname,
                    severity=getattr(alert_data.labels, 'severity', None),
                    instance=getattr(alert_data.labels, 'instance', None),
                    labels=alert_data.labels.model_dump(mode='json'),
                    annotations=alert_data.annotations.model_dump(mode='json') if alert_data.annotations else None,
                    starts_at=alert_data.startsAt,
                    ends_at=alert_data.endsAt,
                    raw_data=alert_data.model_dump(mode='json')
                )
                db.add(alert)
                db.flush()  # Flush to get the alert ID
                logger.info(f"Created new alert: {alert_data.fingerprint}")
                alert_ids.append(alert.id)
            
        except Exception as e:
            logger.error(f"Error storing alert {alert_data.fingerprint}: {e}", exc_info=True)
            # Continue processing other alerts
            continue
    
    # Commit all alerts
    db.commit()
    
    # Queue alerts for processing
    task_ids = []
    if alert_ids:
        try:
            for alert_id in alert_ids:
                result = process_alert.delay(alert_id, request_id)
                task_ids.append(result.id)
            
            logger.info(
                f"Queued {len(alert_ids)} alerts for processing",
                extra={"request_id": request_id, "task_count": len(task_ids)}
            )
            
        except Exception as e:
            logger.error(f"Error queuing alerts for processing: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to queue alerts for processing")
    
    return WebhookResponse(
        status="accepted",
        request_id=request_id,
        alerts_received=len(webhook.alerts),
        task_ids=task_ids,
        message=f"Successfully received and queued {len(webhook.alerts)} alerts"
    )


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by alert status (firing/resolved)"),
    alert_name: Optional[str] = Query(None, description="Filter by alert name"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(100, le=1000, description="Maximum number of alerts to return"),
    offset: int = Query(0, ge=0, description="Number of alerts to skip"),
    db: Session = Depends(get_db)
) -> List[AlertResponse]:
    """List alerts with optional filtering."""
    
    query = db.query(Alert)
    
    # Apply filters
    if status:
        query = query.filter(Alert.status == status)
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
    fingerprint: str,
    request: Request,
    db: Session = Depends(get_db)
) -> WebhookResponse:
    """Retry processing for a specific alert."""
    
    request_id = get_request_id(request)
    
    alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Queue for processing
    result = process_alert.delay(alert.id, request_id)
    
    logger.info(f"Queued alert for retry: {fingerprint}", extra={"request_id": request_id})
    
    return WebhookResponse(
        status="queued",
        request_id=request_id,
        alerts_received=1,
        task_ids=[result.id],
        message=f"Alert {fingerprint} queued for retry"
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)) -> TaskStatusResponse:
    """Get the status of a Celery task from the database."""
    
    # Query TaskResult table first
    task_result = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
    
    if task_result:
        return TaskStatusResponse(
            task_id=task_id,
            status=task_result.status,
            result=task_result.result,
            error=task_result.traceback if task_result.status == 'FAILURE' else None
        )
    
    # Fallback to Celery result backend
    result = AsyncResult(task_id, app=celery_app)
    
    return TaskStatusResponse(
        task_id=task_id,
        status=result.status,
        result=result.result if result.ready() and result.successful() else None,
        error=str(result.info) if result.ready() and not result.successful() else None
    )


@router.get("/requests/{request_id}/tasks")
def get_request_tasks(
    request_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get all tasks associated with a request_id."""
    
    tasks = db.query(TaskResult).filter(
        TaskResult.request_id == request_id
    ).order_by(TaskResult.date_created).all()
    
    return {
        "request_id": request_id,
        "task_count": len(tasks),
        "tasks": [
            {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "status": task.status,
                "alert_id": task.alert_id,
                "date_created": task.date_created.isoformat() if task.date_created else None,
                "date_started": task.date_started.isoformat() if task.date_started else None,
                "date_done": task.date_done.isoformat() if task.date_done else None,
                "result": task.result,
                "error": task.traceback if task.status == 'FAILURE' else None
            }
            for task in tasks
        ]
    }


@router.get("/requests/{request_id}/status")
def get_request_status(
    request_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get complete status of a request including API call, alerts, tasks, and ST2 executions."""
    
    # Get API call
    api_call = db.query(APICall).filter(APICall.request_id == request_id).first()
    if not api_call:
        raise HTTPException(status_code=404, detail="Request ID not found")
    
    # Get alerts
    alerts = db.query(Alert).filter(Alert.api_call_id == api_call.id).all()
    
    # Get tasks
    tasks = db.query(TaskResult).filter(TaskResult.request_id == request_id).all()
    
    # Get ST2 execution links
    st2_executions = db.query(ST2ExecutionLink).filter(
        ST2ExecutionLink.request_id == request_id
    ).all()
    
    return {
        "request_id": request_id,
        "api_call": {
            "method": api_call.method,
            "path": api_call.path,
            "status_code": api_call.status_code,
            "created_at": api_call.created_at.isoformat() if api_call.created_at else None,
            "completed_at": api_call.completed_at.isoformat() if api_call.completed_at else None,
        },
        "alerts": [
            {
                "id": alert.id,
                "fingerprint": alert.fingerprint,
                "alert_name": alert.alert_name,
                "status": alert.status,
                "severity": alert.severity,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
            }
            for alert in alerts
        ],
        "tasks": [
            {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "status": task.status,
                "alert_id": task.alert_id,
                "date_created": task.date_created.isoformat() if task.date_created else None,
                "date_done": task.date_done.isoformat() if task.date_done else None,
            }
            for task in tasks
        ],
        "st2_executions": [
            {
                "st2_execution_id": execution.st2_execution_id,
                "st2_action_ref": execution.st2_action_ref,
                "alert_id": execution.alert_id,
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
            }
            for execution in st2_executions
        ],
        "summary": {
            "alert_count": len(alerts),
            "task_count": len(tasks),
            "st2_execution_count": len(st2_executions),
            "tasks_pending": sum(1 for t in tasks if t.status == 'PENDING'),
            "tasks_started": sum(1 for t in tasks if t.status == 'STARTED'),
            "tasks_success": sum(1 for t in tasks if t.status == 'SUCCESS'),
            "tasks_failed": sum(1 for t in tasks if t.status == 'FAILURE'),
        }
    }

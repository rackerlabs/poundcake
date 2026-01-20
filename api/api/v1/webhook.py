"""Simplified webhook endpoint - Uses Celery for async ST2 triggering."""

from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
import uuid
from datetime import datetime

from api.core.database import get_db
from api.models.models_simple import APICall, Alert, ST2ExecutionLink
from api.tasks.tasks_simple import process_alert

router = APIRouter()


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Alertmanager webhook and queue processing.

    Flow:
    1. Generate request_id
    2. Store API call + alerts in database
    3. Queue Celery task to trigger StackStorm
    4. Return 202 Accepted immediately

    The Celery task will:
    - Determine appropriate ST2 workflow
    - Call ST2 API
    - Store execution link

    Returns:
        dict: Response with request_id and status
    """
    # Generate unique request_id for tracking
    request_id = str(uuid.uuid4())

    # Get request data
    body = await request.json()
    headers = dict(request.headers)

    # Store API call
    api_call = APICall(
        request_id=request_id,
        method=request.method,
        path=str(request.url.path),
        headers=headers,
        body=body,
        client_host=request.client.host if request.client else None,
        status_code=202,  # Accepted
    )
    db.add(api_call)
    db.flush()

    # Process alerts from Alertmanager payload
    alerts_data = body.get("alerts", [])
    alert_ids = []

    for alert_data in alerts_data:
        labels = alert_data.get("labels", {})
        annotations = alert_data.get("annotations", {})

        # Create alert record
        alert = Alert(
            api_call_id=api_call.id,
            fingerprint=alert_data.get("fingerprint", ""),
            status=alert_data.get("status", ""),
            alert_name=labels.get("alertname", "Unknown"),
            severity=labels.get("severity", ""),
            instance=labels.get("instance", ""),
            labels=labels,
            annotations=annotations,
            raw_data=alert_data,
            starts_at=alert_data.get("startsAt"),
            ends_at=alert_data.get("endsAt"),
        )
        db.add(alert)
        db.flush()

        alert_ids.append(alert.id)

        # Queue Celery task to process this alert
        process_alert.delay(alert_id=alert.id, request_id=request_id)

    # Mark API call as completed
    api_call.completed_at = datetime.utcnow()
    db.commit()

    return {
        "status": "accepted",
        "request_id": request_id,
        "alerts_received": len(alerts_data),
        "message": f"Received {len(alerts_data)} alert(s), queued for processing",
    }


@router.get("/status/{request_id}")
async def get_request_status(request_id: str, db: Session = Depends(get_db)):
    """Get complete status of a request including ST2 executions.

    This provides the full audit trail:
    - Original webhook request
    - Alerts received
    - StackStorm executions triggered

    Args:
        request_id: The request_id to look up

    Returns:
        dict: Complete status including ST2 execution IDs
    """
    # Get API call
    api_call = db.query(APICall).filter(APICall.request_id == request_id).first()

    if not api_call:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    # Get alerts
    alerts = db.query(Alert).filter(Alert.api_call_id == api_call.id).all()

    # Get ST2 execution links
    links = db.query(ST2ExecutionLink).filter(ST2ExecutionLink.request_id == request_id).all()

    return {
        "request_id": request_id,
        "received_at": api_call.created_at.isoformat(),
        "completed_at": api_call.completed_at.isoformat() if api_call.completed_at else None,
        "processing_time_ms": api_call.processing_time_ms,
        "alerts": [
            {
                "id": alert.id,
                "fingerprint": alert.fingerprint,
                "alert_name": alert.alert_name,
                "severity": alert.severity,
                "instance": alert.instance,
                "status": alert.status,
                "st2_workflow": alert.st2_rule_matched,
            }
            for alert in alerts
        ],
        "stackstorm_executions": [
            {
                "st2_execution_id": link.st2_execution_id,
                "st2_workflow": link.st2_action_ref,
                "alert_id": link.alert_id,
                "triggered_at": link.created_at.isoformat(),
            }
            for link in links
        ],
    }


@router.get("/executions/recent")
async def list_recent_executions(limit: int = 20, db: Session = Depends(get_db)):
    """List recent webhook requests and their ST2 executions.

    Args:
        limit: Maximum number of results to return

    Returns:
        dict: List of recent executions with summary info
    """
    api_calls = db.query(APICall).order_by(APICall.created_at.desc()).limit(limit).all()

    result = []
    for api_call in api_calls:
        alerts = db.query(Alert).filter(Alert.api_call_id == api_call.id).all()

        links = (
            db.query(ST2ExecutionLink)
            .filter(ST2ExecutionLink.request_id == api_call.request_id)
            .all()
        )

        result.append(
            {
                "request_id": api_call.request_id,
                "received_at": api_call.created_at.isoformat(),
                "alert_count": len(alerts),
                "st2_execution_count": len(links),
                "alerts": [
                    {
                        "name": a.alert_name,
                        "severity": a.severity,
                        "st2_workflow": a.st2_rule_matched,
                    }
                    for a in alerts
                ],
            }
        )

    return {"executions": result, "total": len(result)}


@router.get("/alerts/active")
async def list_active_alerts(db: Session = Depends(get_db)):
    """List all active (firing) alerts.

    Returns:
        dict: List of currently active alerts
    """
    alerts = (
        db.query(Alert).filter(Alert.status == "firing").order_by(Alert.created_at.desc()).all()
    )

    return {
        "active_alerts": [
            {
                "fingerprint": a.fingerprint,
                "alert_name": a.alert_name,
                "severity": a.severity,
                "instance": a.instance,
                "starts_at": a.starts_at.isoformat() if a.starts_at else None,
                "st2_workflow": a.st2_rule_matched,
            }
            for a in alerts
        ],
        "count": len(alerts),
    }


@router.get("/st2/executions")
async def list_st2_executions(limit: int = 50, db: Session = Depends(get_db)):
    """List all ST2 execution links.

    This shows all StackStorm executions triggered by PoundCake.

    Args:
        limit: Maximum number of results

    Returns:
        dict: List of ST2 execution links with alert context
    """
    links = (
        db.query(ST2ExecutionLink).order_by(ST2ExecutionLink.created_at.desc()).limit(limit).all()
    )

    result = []
    for link in links:
        alert = db.query(Alert).filter(Alert.id == link.alert_id).first()

        result.append(
            {
                "request_id": link.request_id,
                "st2_execution_id": link.st2_execution_id,
                "st2_workflow": link.st2_action_ref,
                "st2_rule": link.st2_rule_ref,
                "triggered_at": link.created_at.isoformat(),
                "alert": (
                    {
                        "name": alert.alert_name if alert else None,
                        "severity": alert.severity if alert else None,
                        "instance": alert.instance if alert else None,
                    }
                    if alert
                    else None
                ),
            }
        )

    return {"st2_executions": result, "count": len(result)}


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint.

    Returns:
        dict: Health status
    """
    try:
        # Test database connection
        db.execute("SELECT 1")

        return {"status": "healthy", "database": "connected", "service": "poundcake-api"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

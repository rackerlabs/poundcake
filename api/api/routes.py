"""API routes for webhook and alert management."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc

from api.core.database import get_db
from api.core.middleware import get_req_id
from api.core.logging import get_logger
from api.models.models import Alert, Recipe, Oven
from api.schemas.schemas import (
    AlertmanagerWebhook,
    WebhookResponse,
    AlertResponse,
)
from api.services import pre_heat, determine_recipe, execute_recipe

logger = get_logger(__name__)
router = APIRouter()


@router.post("/webhook", response_model=WebhookResponse, status_code=202)
async def receive_alertmanager_webhook(
    webhook: AlertmanagerWebhook, 
    request: Request, 
    background_tasks: BackgroundTasks,
) -> WebhookResponse:
    """
    Receive Alertmanager webhook and respond immediately.

    Flow:
    1. Alertmanager posts to /webhook
    2. PreHeatMiddleware generates req_id
    3. PoundCake responds with 202 and req_id
    4. Payload is dispatched to pre_heat for background processing
    
    Note: This endpoint does NOT trigger recipe execution.
    Use POST /api/v1/alerts/process to trigger processing.
    """
    req_id = get_req_id(request)

    logger.info(
        f"Received Alertmanager webhook with {len(webhook.alerts)} alerts",
        extra={"req_id": req_id},
    )

    if not webhook.alerts:
        return WebhookResponse(
            status="no_alerts",
            request_id=req_id,
            alerts_received=0,
            task_ids=[],
            message="No alerts in webhook payload",
        )

    # Dispatch to background processing
    # Note: background task will create its own DB session
    background_tasks.add_task(_process_webhook_background, webhook, req_id)

    # Return 202 immediately
    return WebhookResponse(
        status="accepted",
        request_id=req_id,
        alerts_received=len(webhook.alerts),
        task_ids=[],
        message=f"Accepted {len(webhook.alerts)} alerts for processing",
    )


def _process_webhook_background(webhook: AlertmanagerWebhook, req_id: str):
    """Background task to process webhook after 202 response is sent.
    
    This function creates its own database session to avoid issues with
    the request-scoped session being closed.
    """
    from api.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        pre_heat(webhook, req_id, db)
        logger.info(
            f"Background processing complete for req_id: {req_id}",
            extra={"req_id": req_id}
        )
    except Exception as e:
        logger.error(
            f"Background processing failed for req_id {req_id}: {e}",
            exc_info=True,
            extra={"req_id": req_id}
        )
    finally:
        db.close()


@router.get("/alerts", response_model=List[AlertResponse])
def get_alerts(
    req_id: Optional[str] = Query(None, description="Filter by request ID"),
    fingerprint: Optional[str] = Query(None, description="Filter by fingerprint"),
    name: Optional[str] = Query(None, description="Filter by alert name"),
    processing_status: Optional[str] = Query(None, description="Filter by processing status"),
    alert_status: Optional[str] = Query(None, description="Filter by alert status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(100, le=1000, description="Maximum number of alerts to return"),
    offset: int = Query(0, ge=0, description="Number of alerts to skip"),
    db: Session = Depends(get_db),
) -> List[AlertResponse]:
    """Get alerts with optional filtering.
    
    This consolidated endpoint replaces:
    - GET /alerts/{req_id}
    - GET /alerts/{fingerprint}
    - GET /alerts/{name}
    
    Use query parameters to filter results.
    """

    query = db.query(Alert)

    # Apply filters
    if req_id:
        query = query.filter(Alert.req_id == req_id)
    if fingerprint:
        query = query.filter(Alert.fingerprint == fingerprint)
    if name:
        query = query.filter(Alert.alert_name == name)
    if processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    if alert_status:
        query = query.filter(Alert.alert_status == alert_status)
    if severity:
        query = query.filter(Alert.severity == severity)

    # Order by created_at descending
    query = query.order_by(desc(Alert.created_at))

    # Apply pagination
    alerts = query.offset(offset).limit(limit).all()

    return alerts


@router.post("/alerts/process", status_code=202)
async def process_alerts(
    request: Request,
    fingerprints: Optional[List[str]] = Query(None, description="Specific fingerprints to process"),
    processing_status: Optional[str] = Query("new", description="Process alerts with this status"),
    db: Session = Depends(get_db),
) -> dict:
    """Process alerts by executing their recipes.
    
    This endpoint:
    1. Queries alerts based on filters
    2. Determines appropriate recipe for each alert
    3. Creates ovens and executes recipes (using alert's original req_id)
    4. Returns 202 Accepted
    
    Note: This endpoint does NOT generate a new req_id. It uses the req_id 
    from each alert (which was set when the webhook was received).
    
    Args:
        fingerprints: Optional list of specific alert fingerprints to process
        processing_status: Process alerts with this status (default: "new")
    """
    # Build query
    query = db.query(Alert)
    
    if fingerprints:
        query = query.filter(Alert.fingerprint.in_(fingerprints))
    elif processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    else:
        # Default to processing only "new" alerts
        query = query.filter(Alert.processing_status == "new")
    
    alerts = query.all()
    
    if not alerts:
        return {
            "status": "no_alerts",
            "message": "No alerts found matching criteria"
        }
    
    processed_count = 0
    execution_ids = []
    processed_req_ids = set()  # Track unique req_ids processed
    
    for alert in alerts:
        try:
            # Use the req_id from the alert (set during webhook ingestion)
            alert_req_id = alert.req_id
            processed_req_ids.add(alert_req_id)
            
            # Determine recipe
            recipe = determine_recipe(alert.alert_name, db)
            if not recipe:
                logger.warning(
                    f"No recipe found for alert: {alert.alert_name}",
                    extra={"req_id": alert_req_id, "fingerprint": alert.fingerprint}
                )
                continue
            
            # Create oven (using alert's req_id)
            oven = Oven(
                req_id=alert_req_id,  # Use alert's original req_id
                alert_id=alert.id,
                recipe_id=recipe.id,
                status="new",
            )
            db.add(oven)
            db.commit()
            db.refresh(oven)
            
            # Execute recipe (using alert's req_id)
            success = execute_recipe(oven, recipe, alert, alert_req_id, db)
            
            if success:
                alert.processing_status = "processing"
                db.commit()
                processed_count += 1
                if oven.action_id:
                    execution_ids.append(oven.action_id)
        
        except Exception as e:
            logger.error(
                f"Error processing alert {alert.fingerprint}: {e}",
                exc_info=True,
                extra={"req_id": alert.req_id}
            )
            continue
    
    return {
        "status": "accepted",
        "req_ids": list(processed_req_ids),  # Return the alert req_ids, not a new one
        "alerts_processed": processed_count,
        "execution_ids": execution_ids,
        "message": f"Processed {processed_count} of {len(alerts)} alerts"
    }


@router.get("/executions/{req_id}")
def get_executions_by_request(req_id: str, db: Session = Depends(get_db)):
    """Get all executions (ovens) for a specific request ID.
    
    This provides a complete audit trail of all recipe executions
    that were triggered by a specific webhook request.
    """
    ovens = db.query(Oven).filter(Oven.req_id == req_id).all()
    
    if not ovens:
        raise HTTPException(status_code=404, detail="No executions found for this request ID")
    
    results = []
    for oven in ovens:
        results.append({
            "oven_id": oven.id,
            "req_id": oven.req_id,
            "status": oven.status,
            "recipe_name": oven.recipe.name if oven.recipe else None,
            "st2_workflow": oven.recipe.st2_workflow_ref if oven.recipe else None,
            "st2_execution_id": oven.action_id,
            "alert_name": oven.alert.alert_name if oven.alert else None,
            "started_at": oven.started_at,
            "ended_at": oven.ended_at,
            "action_result": oven.action_result,
        })
    
    return {
        "req_id": req_id,
        "total_executions": len(results),
        "executions": results
    }

#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes for webhook and alert management."""

import os
import requests
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc

from api.core.database import get_db
from api.core.middleware import get_req_id
from api.core.logging import get_logger
from api.models.models import Alert, Oven, Recipe
from api.schemas.schemas import (
    AlertmanagerWebhook,
    WebhookResponse,
    AlertResponse,
)
from api.services import pre_heat

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
            f"Background processing complete for req_id: {req_id}", extra={"req_id": req_id}
        )
    except Exception as e:
        logger.error(
            f"Background processing failed for req_id {req_id}: {e}",
            exc_info=True,
            extra={"req_id": req_id},
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
    alert_id: Optional[int] = Body(
        None, description="Specific alert ID to process (for oven service)"
    ),
    recipe_id: Optional[int] = Body(None, description="Specific recipe ID (for oven service)"),
    task_id: Optional[str] = Body(None, description="Specific task UUID from recipe.task_list"),
    fingerprints: Optional[List[str]] = Query(
        None, description="Specific fingerprints to process (bulk mode)"
    ),
    processing_status: Optional[str] = Query(
        "new", description="Process alerts with this status (bulk mode)"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Process alerts by executing their recipes.

    Two modes of operation:

    1. BULK MODE (called manually or by external systems):
       - Queries alerts based on filters (fingerprints or processing_status)
       - For each alert, matches recipe by group_name
       - Parses task_list and creates one oven per task
       - Executes each task via StackStorm

    2. TASK MODE (called by oven service):
       - Processes a specific alert_id + recipe_id + task_id combination
       - Creates single oven entry for that task
       - Executes the task via StackStorm
       - Updates alert processing_status only on first task

    Args:
        alert_id: Specific alert to process (task mode)
        recipe_id: Specific recipe to use (task mode)
        task_id: Specific task UUID from recipe.task_list (task mode)
        fingerprints: Optional list of fingerprints (bulk mode)
        processing_status: Process alerts with this status (bulk mode)
    """

    # Task mode: Process specific alert + recipe + task
    if alert_id is not None and recipe_id is not None and task_id is not None:
        return await _process_single_task(alert_id, recipe_id, task_id, db)

    # Bulk mode: Process multiple alerts
    return await _process_alerts_bulk(fingerprints, processing_status, db)


async def _process_single_task(alert_id: int, recipe_id: int, task_id: str, db: Session) -> dict:
    """Process a single task for a specific alert (called by oven service).

    Steps:
    1. Get alert and recipe from database
    2. Create oven entry with task_id and status='new'
    3. Update alert.processing_status to 'processing' (if first task)
    4. Call StackStorm API with task_id
    5. Store execution_id in oven.action_id
    6. Update oven.status to 'processing'
    """
    # Get alert
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    # Get recipe
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")

    req_id = alert.req_id

    logger.info(
        f"Processing task {task_id} for alert {alert_id}",
        extra={"req_id": req_id, "alert_id": alert_id, "recipe_id": recipe_id},
    )

    # Create oven entry
    oven = Oven(
        req_id=req_id,
        alert_id=alert_id,
        recipe_id=recipe_id,
        task_id=task_id,
        status="new",
    )
    db.add(oven)
    db.commit()
    db.refresh(oven)

    # Update alert status to processing (if not already)
    if alert.processing_status == "new":
        alert.processing_status = "processing"
        db.commit()

    # Execute task via StackStorm
    success, execution_id, result = _execute_stackstorm_task(
        recipe=recipe, alert=alert, task_id=task_id, req_id=req_id
    )

    # Update oven with results
    oven.action_id = execution_id
    oven.action_result = result
    oven.status = "processing" if success else "failed"
    oven.started_at = datetime.utcnow()

    if not success:
        oven.ended_at = datetime.utcnow()
        oven.status = "complete"

    db.commit()

    return {
        "status": "accepted",
        "req_id": req_id,
        "alert_id": alert_id,
        "recipe_id": recipe_id,
        "task_id": task_id,
        "oven_id": oven.id,
        "execution_id": execution_id,
        "success": success,
    }


async def _process_alerts_bulk(
    fingerprints: Optional[List[str]], processing_status: Optional[str], db: Session
) -> dict:
    """Process multiple alerts in bulk mode.

    For each alert:
    1. Match recipe by group_name
    2. Parse task_list
    3. Create one oven per task
    4. Execute each task
    """
    # Build query
    query = db.query(Alert)

    if fingerprints:
        query = query.filter(Alert.fingerprint.in_(fingerprints))
    elif processing_status:
        query = query.filter(Alert.processing_status == processing_status)
    else:
        query = query.filter(Alert.processing_status == "new")

    alerts = query.all()

    if not alerts:
        return {"status": "no_alerts", "message": "No alerts found matching criteria"}

    processed_count = 0
    tasks_triggered = 0
    execution_ids = []
    processed_req_ids = set()

    for alert in alerts:
        try:
            alert_req_id = alert.req_id
            processed_req_ids.add(alert_req_id)

            # Match recipe by group_name
            recipe = _determine_recipe_by_group_name(alert.group_name, db)
            if not recipe:
                logger.warning(
                    f"No recipe found for group_name: {alert.group_name}",
                    extra={"req_id": alert_req_id, "alert_id": alert.id},
                )
                continue

            # Parse task_list
            tasks = _parse_task_list(recipe.task_list)
            if not tasks:
                logger.warning(
                    f"Recipe {recipe.id} has empty task_list", extra={"req_id": alert_req_id}
                )
                continue

            logger.info(
                f"Processing alert {alert.id} with recipe {recipe.name} ({len(tasks)} tasks)",
                extra={"req_id": alert_req_id},
            )

            # Update alert status
            alert.processing_status = "processing"
            db.commit()

            # Process each task
            for task_id in tasks:
                try:
                    # Create oven
                    oven = Oven(
                        req_id=alert_req_id,
                        alert_id=alert.id,
                        recipe_id=recipe.id,
                        task_id=task_id,
                        status="new",
                    )
                    db.add(oven)
                    db.commit()
                    db.refresh(oven)

                    # Execute via StackStorm
                    success, execution_id, result = _execute_stackstorm_task(
                        recipe=recipe, alert=alert, task_id=task_id, req_id=alert_req_id
                    )

                    # Update oven
                    oven.action_id = execution_id
                    oven.action_result = result
                    oven.status = "processing" if success else "failed"
                    oven.started_at = datetime.utcnow()

                    if not success:
                        oven.ended_at = datetime.utcnow()
                        oven.status = "complete"

                    db.commit()

                    if success and execution_id:
                        execution_ids.append(execution_id)

                    tasks_triggered += 1

                except Exception as e:
                    logger.error(
                        f"Error processing task {task_id}: {e}",
                        exc_info=True,
                        extra={"req_id": alert_req_id},
                    )
                    continue

            processed_count += 1

        except Exception as e:
            logger.error(
                f"Error processing alert {alert.id}: {e}",
                exc_info=True,
                extra={"req_id": alert.req_id},
            )
            continue

    return {
        "status": "accepted",
        "req_ids": list(processed_req_ids),
        "alerts_processed": processed_count,
        "tasks_triggered": tasks_triggered,
        "execution_ids": execution_ids,
        "message": f"Processed {processed_count} alerts with {tasks_triggered} tasks",
    }


def _determine_recipe_by_group_name(group_name: Optional[str], db: Session) -> Optional[Recipe]:
    """Determine which recipe to use based on alert group_name.

    Matching logic:
    1. Exact match on recipe.name = group_name
    2. Pattern match (lowercase, underscore-normalized)
    3. Fallback to "default" recipe

    Args:
        group_name: Group name from alert (from groupLabels.alertname)
        db: Database session

    Returns:
        Recipe object if found, None otherwise
    """
    if not group_name:
        # Try default recipe
        return db.query(Recipe).filter(Recipe.name == "default").first()

    # Try exact match
    recipe = db.query(Recipe).filter(Recipe.name == group_name).first()
    if recipe:
        return recipe

    # Try pattern matching
    pattern = group_name.lower().replace(" ", "_")
    recipe = db.query(Recipe).filter(Recipe.name.like(f"%{pattern}%")).first()
    if recipe:
        return recipe

    # Fallback to default
    recipe = db.query(Recipe).filter(Recipe.name == "default").first()
    return recipe


def _parse_task_list(task_list_str: Optional[str]) -> List[str]:
    """Parse comma-separated task_list into list of task UUIDs.

    Args:
        task_list_str: Comma-separated string like "uuid1,uuid2,uuid3"

    Returns:
        List of task UUID strings
    """
    if not task_list_str:
        return []

    tasks = [task.strip() for task in task_list_str.split(",") if task.strip()]
    return tasks


def _execute_stackstorm_task(
    recipe: Recipe, alert: Alert, task_id: str, req_id: str
) -> tuple[bool, Optional[str], Optional[dict]]:
    """Execute a single task via StackStorm API.

    Args:
        recipe: Recipe containing st2_workflow_ref
        alert: Alert data for parameters
        task_id: Task UUID being executed
        req_id: Request ID for tracking

    Returns:
        Tuple of (success, execution_id, result_dict)
    """
    ST2_API_URL = os.getenv("ST2_API_URL", "http://localhost:9101/v1")
    ST2_API_KEY = os.getenv("ST2_API_KEY", "")

    try:
        # Prepare parameters for StackStorm
        st2_params = {
            "alert_name": alert.alert_name,
            "group_name": alert.group_name,
            "alert_fingerprint": alert.fingerprint,
            "instance": alert.instance,
            "severity": alert.severity,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "req_id": req_id,
            "task_id": task_id,
            "alert_data": alert.raw_data,
        }

        logger.info(
            f"Executing StackStorm workflow: {recipe.st2_workflow_ref} for task {task_id}",
            extra={"req_id": req_id},
        )

        # Call StackStorm API
        response = requests.post(
            f"{ST2_API_URL}/executions",
            json={"action": recipe.st2_workflow_ref, "parameters": st2_params},
            headers={"St2-Api-Key": ST2_API_KEY, "Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code in [200, 201]:
            st2_data = response.json()
            execution_id = st2_data.get("id")

            logger.info(f"StackStorm execution started: {execution_id}", extra={"req_id": req_id})

            return True, execution_id, st2_data
        else:
            logger.error(
                f"StackStorm API error: {response.status_code} - {response.text}",
                extra={"req_id": req_id},
            )

            return (
                False,
                None,
                {
                    "error": f"ST2 API returned {response.status_code}",
                    "response": response.text[:500],
                },
            )

    except Exception as e:
        logger.error(f"Error calling StackStorm API: {e}", exc_info=True, extra={"req_id": req_id})

        return False, None, {"error": str(e)}


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
        results.append(
            {
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
            }
        )

    return {"req_id": req_id, "total_executions": len(results), "executions": results}

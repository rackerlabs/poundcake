"""Oven service for recipe execution and management."""

import os
from datetime import datetime
from typing import Optional
import requests
from sqlalchemy.orm import Session

from api.core.logging import get_logger
from api.models.models import Alert, Recipe, Oven

logger = get_logger(__name__)


def determine_recipe(alert_name: str, db: Session) -> Optional[Recipe]:
    """Determine which recipe to use for an alert.

    This function matches alert names to recipes. You can customize the matching logic:
    - Exact match
    - Pattern matching
    - Severity-based fallback

    Args:
        alert_name: Name of the alert from Alertmanager
        db: Database session

    Returns:
        Recipe object if found, None otherwise
    """
    # Try exact match first
    recipe = db.query(Recipe).filter(Recipe.name == alert_name).first()
    if recipe:
        return recipe

    # Try pattern matching
    # Example: "HostDown" matches "host_down_workflow"
    pattern = alert_name.lower().replace(" ", "_")
    recipe = db.query(Recipe).filter(Recipe.name.like(f"%{pattern}%")).first()
    if recipe:
        return recipe

    # Fallback to default recipe
    recipe = db.query(Recipe).filter(Recipe.name == "default").first()
    return recipe


def execute_recipe(oven: Oven, recipe: Recipe, alert: Alert, req_id: str, db: Session) -> bool:
    """Execute a recipe by triggering StackStorm workflow.

    Args:
        oven: Oven instance to track execution
        recipe: Recipe to execute
        alert: Alert that triggered the execution
        req_id: Request ID for tracking
        db: Database session

    Returns:
        True if execution successful, False otherwise
    """
    ST2_API_URL = os.getenv("ST2_API_URL", "http://localhost:9101/v1")
    ST2_API_KEY = os.getenv("ST2_API_KEY", "")

    try:
        # Update oven status to processing
        oven.status = "processing"
        oven.started_at = datetime.utcnow()
        db.commit()

        # Prepare StackStorm execution parameters
        st2_params = {
            "alert_name": alert.alert_name,
            "alert_fingerprint": alert.fingerprint,
            "instance": alert.instance,
            "severity": alert.severity,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "req_id": req_id,
            "alert_data": alert.raw_data,
        }

        logger.info(
            f"Executing recipe: {recipe.name} -> {recipe.st2_workflow_ref}",
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
            st2_execution_id = st2_data.get("id")

            # Update oven with execution result
            oven.action_id = st2_execution_id
            oven.action_result = st2_data
            oven.status = "complete"
            oven.ended_at = datetime.utcnow()
            db.commit()

            logger.info(
                f"Recipe execution complete: ST2 execution {st2_execution_id}",
                extra={"req_id": req_id},
            )
            return True
        else:
            # Execution failed
            logger.error(
                f"ST2 API error: {response.status_code} - {response.text}", extra={"req_id": req_id}
            )
            oven.status = "complete"
            oven.action_result = {
                "error": f"ST2 API returned {response.status_code}",
                "response": response.text[:500],
            }
            oven.ended_at = datetime.utcnow()
            db.commit()
            return False

    except Exception as e:
        logger.error(f"Error executing recipe: {e}", exc_info=True, extra={"req_id": req_id})
        oven.status = "complete"
        oven.action_result = {"error": str(e)}
        oven.ended_at = datetime.utcnow()
        db.commit()
        return False

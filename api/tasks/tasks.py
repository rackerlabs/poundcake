"""Simplified Celery tasks - Just trigger StackStorm and track execution links.

No more:
- Complex action execution
- CAB step processing
- Action parameter templating

Now:
- Receive alert
- Determine ST2 workflow
- Trigger ST2 via API
- Store link (request_id ↔ st2_execution_id)
"""

from celery import Celery
from sqlalchemy.orm import Session
import requests
import os
from typing import Dict, Any

from api.core.database import SessionLocal
from api.models.models import Alert, ST2ExecutionLink

# Initialize Celery
celery_app = Celery(
    "poundcake",
    broker=os.getenv("POUNDCAKE_CELERY_BROKER_URL", os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")),
    backend=os.getenv("POUNDCAKE_CELERY_RESULT_BACKEND", os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")),
)

# StackStorm configuration
ST2_API_URL = os.getenv("POUNDCAKE_STACKSTORM_URL", os.getenv("ST2_API_URL", "http://localhost:9101/v1"))
ST2_API_KEY = os.getenv("POUNDCAKE_STACKSTORM_API_KEY", os.getenv("ST2_API_KEY", ""))


def determine_st2_workflow(alert_data: Dict[str, Any]) -> str:
    """Determine which StackStorm workflow to trigger.

    This is simple pattern matching. Customize based on your ST2 workflows.

    Examples:
    - HostDown → remediation.host_down_workflow
    - HighMemory → remediation.memory_check_workflow
    - DiskFull → remediation.disk_cleanup_workflow
    """
    labels = alert_data.get("labels", {})
    alert_name = labels.get("alertname", "")
    severity = labels.get("severity", "")

    # Map alert patterns to ST2 workflows
    workflow_map = {
        "HostDown": "remediation.host_down_workflow",
        "NodeDown": "remediation.host_down_workflow",
        "HighMemory": "remediation.memory_check_workflow",
        "HighCPU": "remediation.cpu_check_workflow",
        "DiskFull": "remediation.disk_cleanup_workflow",
        "ServiceDown": "remediation.service_restart_workflow",
    }

    # Check for exact matches
    for pattern, workflow in workflow_map.items():
        if pattern in alert_name:
            return workflow

    # Fallback based on severity
    if severity == "critical":
        return "remediation.critical_alert_workflow"
    elif severity == "warning":
        return "remediation.warning_alert_workflow"
    else:
        return "remediation.default_workflow"


@celery_app.task(name="process_alert", bind=True)
def process_alert(self, alert_id: int, request_id: str):
    """Process alert by triggering StackStorm workflow.

    This is the ONLY Celery task we need!

    Steps:
    1. Get alert from database
    2. Determine which ST2 workflow to trigger
    3. Call ST2 API
    4. Store execution link

    Args:
        alert_id: Database ID of the alert
        request_id: PoundCake request_id for tracking
    """
    db: Session = SessionLocal()

    try:
        # Get alert
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            print(f"✗ Alert {alert_id} not found")
            return {"success": False, "error": "Alert not found"}

        # Update processing status
        alert.processing_status = "processing"
        alert.task_id = self.request.id
        db.commit()

        # Determine ST2 workflow
        alert_data = alert.raw_data or {}
        st2_workflow = determine_st2_workflow(alert_data)

        print(f"→ Processing alert: {alert.alert_name}")
        print(f"→ Triggering ST2 workflow: {st2_workflow}")

        # Prepare ST2 execution parameters
        st2_params = {
            "alert_name": alert.alert_name,
            "instance": alert.instance,
            "severity": alert.severity,
            "fingerprint": alert.fingerprint,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "poundcake_request_id": request_id,  # ← Pass request_id to ST2
            "alert_data": alert_data,
        }

        # Call StackStorm API
        response = requests.post(
            f"{ST2_API_URL}/executions",
            json={"action": st2_workflow, "parameters": st2_params},
            headers={"St2-Api-Key": ST2_API_KEY, "Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code in [200, 201]:
            st2_data = response.json()
            st2_execution_id = st2_data.get("id")

            # Store the link
            link = ST2ExecutionLink(
                request_id=request_id,
                alert_id=alert_id,
                st2_execution_id=st2_execution_id,
                st2_action_ref=st2_workflow,
            )
            db.add(link)

            # Update alert with ST2 rule
            alert.st2_rule_matched = st2_workflow

            db.commit()

            # Update alert status to completed
            alert.processing_status = "completed"
            db.commit()

            print(f"✓ ST2 execution created: {st2_execution_id}")
            print(f"✓ Link stored: {request_id} ↔ {st2_execution_id}")

            return {
                "success": True,
                "st2_execution_id": st2_execution_id,
                "st2_workflow": st2_workflow,
            }
        else:
            # Update alert status to failed
            alert.processing_status = "failed"
            alert.error_message = f"ST2 API returned {response.status_code}: {response.text[:500]}"
            db.commit()

            print(f"✗ ST2 API error: {response.status_code}")
            print(f"✗ Response: {response.text}")
            return {"success": False, "error": f"ST2 API returned {response.status_code}"}

    except Exception as e:
        print(f"✗ Error processing alert: {e}")
        db.rollback()

        # Try to update alert status
        try:
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if alert:
                alert.processing_status = "failed"
                alert.error_message = str(e)
                db.commit()
        except Exception:
            pass

        return {"success": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="query_st2_execution_status")
def query_st2_execution_status(st2_execution_id: str):
    """Query StackStorm execution status.

    Optional task to poll ST2 for execution status updates.

    Args:
        st2_execution_id: StackStorm execution ID

    Returns:
        dict: Execution status from ST2
    """
    try:
        response = requests.get(
            f"{ST2_API_URL}/executions/{st2_execution_id}",
            headers={"St2-Api-Key": ST2_API_KEY},
            timeout=10,
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"ST2 API returned {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}


# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=270,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

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
from celery import Celery, Task
from celery.signals import task_prerun, task_postrun, task_failure
from sqlalchemy.orm import Session
import requests
import os
from typing import Dict, Any
from datetime import datetime

from api.core.database import SessionLocal
from api.models.models import Alert, ST2ExecutionLink, TaskResult


# Initialize Celery with database result backend
DATABASE_URL = os.getenv('DATABASE_URL', 'mysql+pymysql://poundcake:poundcake@mariadb:3306/poundcake')
# Use database backend for results (stores in celery_taskmeta table)
CELERY_RESULT_BACKEND = f'db+{DATABASE_URL}'

celery_app = Celery(
    'poundcake',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=CELERY_RESULT_BACKEND
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max
    task_soft_time_limit=240,  # 4 minutes soft limit
    result_expires=86400,  # Results expire after 24 hours
)


# Custom task class to automatically track request_id
class PoundCakeTask(Task):
    """Custom task class that automatically tracks request_id."""
    
    def __call__(self, *args, **kwargs):
        """Store request_id in task context."""
        return super().__call__(*args, **kwargs)


# Celery signal handlers to maintain TaskResult table
@task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **extra):
    """Record task start in TaskResult table."""
    db = SessionLocal()
    try:
        # Extract request_id from kwargs (should be passed by webhook handler)
        request_id = kwargs.get('request_id') or (args[1] if len(args) > 1 else None)
        alert_id = args[0] if args else kwargs.get('alert_id')
        
        if request_id:
            task_result = TaskResult(
                task_id=task_id,
                task_name=task.name,
                request_id=request_id,
                alert_id=alert_id,
                status='STARTED',
                args=list(args) if args else [],
                kwargs=kwargs,
                date_started=datetime.utcnow()
            )
            db.add(task_result)
            db.commit()
    except Exception as e:
        print(f"Error recording task start: {e}")
    finally:
        db.close()


@task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, **extra):
    """Record task completion in TaskResult table."""
    db = SessionLocal()
    try:
        task_result = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
        if task_result:
            task_result.status = 'SUCCESS'
            task_result.result = retval if isinstance(retval, dict) else {'result': str(retval)}
            task_result.date_done = datetime.utcnow()
            db.commit()
    except Exception as e:
        print(f"Error recording task completion: {e}")
    finally:
        db.close()


@task_failure.connect
def task_failure_handler(task_id, exception, args, kwargs, traceback, einfo, **extra):
    """Record task failure in TaskResult table."""
    db = SessionLocal()
    try:
        task_result = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
        if task_result:
            task_result.status = 'FAILURE'
            task_result.result = {'error': str(exception)}
            task_result.traceback = str(traceback)
            task_result.date_done = datetime.utcnow()
            db.commit()
    except Exception as e:
        print(f"Error recording task failure: {e}")
    finally:
        db.close()

# StackStorm configuration
ST2_API_URL = os.getenv("ST2_API_URL", "http://localhost:9101/v1")
ST2_API_KEY = os.getenv("ST2_API_KEY", "")


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


@celery_app.task(name='process_alert')
def process_alert(alert_id: int, request_id: str):
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
            return
        
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
            "alert_data": alert_data
        }
        
        # Call StackStorm API
        response = requests.post(
            f"{ST2_API_URL}/executions",
            json={
                "action": st2_workflow,
                "parameters": st2_params
            },
            headers={
                "St2-Api-Key": ST2_API_KEY,
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            st2_data = response.json()
            st2_execution_id = st2_data.get("id")
            
            # Store the link
            link = ST2ExecutionLink(
                request_id=request_id,
                alert_id=alert_id,
                st2_execution_id=st2_execution_id,
                st2_action_ref=st2_workflow
            )
            db.add(link)
            
            # Update alert with ST2 rule
            alert.st2_rule_matched = st2_workflow
            
            db.commit()
            
            print(f"✓ ST2 execution created: {st2_execution_id}")
            print(f"✓ Link stored: {request_id} ↔ {st2_execution_id}")
            
            return {
                "success": True,
                "st2_execution_id": st2_execution_id,
                "st2_workflow": st2_workflow
            }
        else:
            print(f"✗ ST2 API error: {response.status_code}")
            print(f"✗ Response: {response.text}")
            return {
                "success": False,
                "error": f"ST2 API returned {response.status_code}"
            }
            
    except Exception as e:
        print(f"✗ Error processing alert: {e}")
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        db.close()


@celery_app.task(name='query_st2_execution_status')
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
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"ST2 API returned {response.status_code}"}
            
    except Exception as e:
        return {"error": str(e)}


# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=270,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

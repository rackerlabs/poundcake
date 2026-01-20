"""Alert processing tasks for Celery.

This module provides batch processing and enhanced alert handling.
"""

from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from api.core.database import SessionLocal
from api.models.models import Alert, TaskExecution
from api.tasks.tasks import celery_app, process_alert


@celery_app.task(name="process_alert_batch", bind=True)
def process_alert_batch(self, fingerprints: List[str], request_id: str):
    """Process multiple alerts in a batch.

    Each alert is processed individually via process_alert task.
    This allows for parallel processing while maintaining individual tracking.

    Args:
        fingerprints: List of alert fingerprints to process
        request_id: The request_id for tracking this batch
    """
    db: Session = SessionLocal()
    results = []

    try:
        for fingerprint in fingerprints:
            # Get alert from database
            alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
            if not alert:
                results.append(
                    {"fingerprint": fingerprint, "status": "not_found", "error": "Alert not found"}
                )
                continue

            # Update alert processing status
            alert.processing_status = "processing"
            alert.task_id = self.request.id
            db.commit()

            # Queue individual alert processing
            task = process_alert.delay(alert.id, request_id)

            # Track task execution
            task_exec = TaskExecution(
                task_id=task.id,
                task_name="process_alert",
                alert_fingerprint=fingerprint,
                status="pending",
                args=[alert.id, request_id],
                created_at=datetime.utcnow(),
            )
            db.add(task_exec)

            results.append(
                {
                    "fingerprint": fingerprint,
                    "alert_id": alert.id,
                    "task_id": task.id,
                    "status": "queued",
                }
            )

        db.commit()

        return {
            "batch_size": len(fingerprints),
            "queued": len([r for r in results if r.get("status") == "queued"]),
            "results": results,
        }

    except Exception as e:
        db.rollback()
        return {"error": str(e), "batch_size": len(fingerprints), "results": results}
    finally:
        db.close()


@celery_app.task(name="process_single_alert", bind=True)
def process_single_alert(self, fingerprint: str, request_id: str = None):
    """Process a single alert by fingerprint.

    This is an alternative entry point that looks up the alert by fingerprint
    rather than ID.

    Args:
        fingerprint: Alert fingerprint
        request_id: Optional request_id for tracking
    """
    db: Session = SessionLocal()

    try:
        # Get alert from database
        alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
        if not alert:
            return {"success": False, "error": f"Alert with fingerprint {fingerprint} not found"}

        # Update processing status
        alert.processing_status = "processing"
        alert.task_id = self.request.id
        db.commit()

        # Get request_id from associated API call if not provided
        if not request_id and alert.api_call:
            request_id = alert.api_call.request_id

        # Track task execution
        task_exec = TaskExecution(
            task_id=self.request.id,
            task_name="process_single_alert",
            alert_fingerprint=fingerprint,
            status="started",
            started_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db.add(task_exec)
        db.commit()

        # Process via main task
        result = process_alert(alert.id, request_id or "unknown")

        # Update task execution status
        task_exec.status = "success" if result.get("success") else "failure"
        task_exec.result = result
        task_exec.completed_at = datetime.utcnow()

        # Update alert status
        if result.get("success"):
            alert.processing_status = "completed"
        else:
            alert.processing_status = "failed"
            alert.error_message = result.get("error")

        db.commit()

        return result

    except Exception as e:
        db.rollback()

        # Try to update alert status
        try:
            alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
            if alert:
                alert.processing_status = "failed"
                alert.error_message = str(e)
                db.commit()
        except Exception:
            pass

        return {"success": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="update_alert_status")
def update_alert_status(fingerprint: str, status: str, error_message: str = None):
    """Update an alert's processing status.

    Args:
        fingerprint: Alert fingerprint
        status: New processing status
        error_message: Optional error message
    """
    db: Session = SessionLocal()

    try:
        alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
        if alert:
            alert.processing_status = status
            if error_message:
                alert.error_message = error_message
            db.commit()
            return {"success": True, "fingerprint": fingerprint, "status": status}
        else:
            return {"success": False, "error": "Alert not found"}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()

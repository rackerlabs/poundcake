"""Health check and statistics endpoints."""
from datetime import datetime, timedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from api.core.database import get_db, engine
from api.core.config import settings
from api.schemas.schemas import HealthResponse, StatsResponse
from api.models.models import Alert, APICall
from api.tasks.tasks import celery_app
import redis

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Health check endpoint.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - Celery workers
    """
    
    # Check database
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    # Check Redis
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    # Check Celery workers
    try:
        inspector = celery_app.control.inspect()
        active_workers = inspector.active()
        if active_workers:
            celery_status = f"healthy ({len(active_workers)} workers)"
        else:
            celery_status = "no workers available"
    except Exception as e:
        celery_status = f"unhealthy: {str(e)}"
    
    # Determine overall status
    overall_status = "healthy"
    if "unhealthy" in db_status or "unhealthy" in redis_status or "unhealthy" in celery_status:
        overall_status = "unhealthy"
    elif "no workers" in celery_status:
        overall_status = "degraded"
    
    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_status,
        redis=redis_status,
        celery=celery_status,
        timestamp=datetime.utcnow()
    )


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Readiness check for Kubernetes."""
    
    try:
        # Check if database is ready
        db.execute(text("SELECT 1"))
        
        # Check if Redis is ready
        r = redis.from_url(settings.redis_url)
        r.ping()
        
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}


@router.get("/health/live")
def liveness_check() -> Dict[str, Any]:
    """Liveness check for Kubernetes."""
    return {"status": "alive"}


@router.get("/stats", response_model=StatsResponse)
def get_statistics(db: Session = Depends(get_db)) -> StatsResponse:
    """Get system statistics."""
    
    # Total counts
    total_api_calls = db.query(func.count(APICall.id)).scalar()
    total_alerts = db.query(func.count(Alert.id)).scalar()
    
    # Alerts by status
    alerts_by_status = dict(
        db.query(Alert.status, func.count(Alert.id))
        .group_by(Alert.status)
        .all()
    )
    
    # Recent alerts (last 24 hours)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_alerts = db.query(func.count(Alert.id)).filter(
        Alert.created_at >= cutoff
    ).scalar()
    
    return StatsResponse(
        total_api_calls=total_api_calls or 0,
        total_alerts=total_alerts or 0,
        alerts_by_status=alerts_by_status,
        alerts_by_processing_status={},  # Removed - no longer tracked
        recent_alerts=recent_alerts or 0
    )


@router.get("/stats/celery")
def get_celery_stats() -> Dict[str, Any]:
    """Get Celery worker statistics."""
    
    try:
        inspector = celery_app.control.inspect()
        
        # Get active tasks
        active = inspector.active()
        active_count = sum(len(tasks) for tasks in active.values()) if active else 0
        
        # Get registered tasks
        registered = inspector.registered()
        
        # Get worker stats
        stats = inspector.stats()
        
        return {
            "status": "available",
            "workers": len(active) if active else 0,
            "active_tasks": active_count,
            "registered_tasks": registered,
            "stats": stats
        }
    except Exception as e:
        return {
            "status": "unavailable",
            "error": str(e)
        }

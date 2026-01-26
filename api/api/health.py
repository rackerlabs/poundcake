"""Health check and statistics endpoints."""

from datetime import datetime, timedelta
from typing import Dict, Any
import os
import requests
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from api.core.database import get_db
from api.core.config import settings
from api.schemas.schemas import HealthResponse, StatsResponse
from api.models.models import Alert, Recipe, Oven

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Health check endpoint.

    Checks:
    - Database connectivity
    - StackStorm API connectivity
    """

    # Check database
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Check StackStorm API
    st2_api_url = os.getenv("ST2_API_URL", "http://localhost:9101/v1")
    try:
        response = requests.get(
            f"{st2_api_url}/actions",
            timeout=5,
            headers={"St2-Api-Key": os.getenv("ST2_API_KEY", "")},
        )
        if response.status_code == 200:
            st2_status = "healthy"
        else:
            st2_status = f"unhealthy: HTTP {response.status_code}"
    except Exception as e:
        st2_status = f"unhealthy: {str(e)}"

    # Determine overall status
    overall_status = "healthy"
    if "unhealthy" in db_status or "unhealthy" in st2_status:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_status,
        stackstorm=st2_status,
        timestamp=datetime.utcnow(),
    )


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Readiness check for Kubernetes."""

    try:
        # Check if database is ready
        db.execute(text("SELECT 1"))

        # Check if StackStorm is ready
        st2_api_url = os.getenv("ST2_API_URL", "http://localhost:9101/v1")
        response = requests.get(
            f"{st2_api_url}/actions",
            timeout=5,
            headers={"St2-Api-Key": os.getenv("ST2_API_KEY", "")},
        )

        if response.status_code != 200:
            return {"status": "not_ready", "error": "StackStorm API not ready"}

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
    total_alerts = db.query(func.count(Alert.id)).scalar()
    total_recipes = db.query(func.count(Recipe.id)).scalar()
    total_executions = db.query(func.count(Oven.id)).scalar()

    # Alerts by processing status
    alerts_by_processing_status = dict(
        db.query(Alert.processing_status, func.count(Alert.id))
        .group_by(Alert.processing_status)
        .all()
    )

    # Alerts by alert status (firing/resolved)
    alerts_by_alert_status = dict(
        db.query(Alert.alert_status, func.count(Alert.id)).group_by(Alert.alert_status).all()
    )

    # Executions by status
    executions_by_status = dict(
        db.query(Oven.status, func.count(Oven.id)).group_by(Oven.status).all()
    )

    # Recent alerts (last 24 hours)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_alerts = db.query(func.count(Alert.id)).filter(Alert.created_at >= cutoff).scalar()

    return StatsResponse(
        total_alerts=total_alerts or 0,
        total_recipes=total_recipes or 0,
        total_executions=total_executions or 0,
        alerts_by_processing_status=alerts_by_processing_status,
        alerts_by_alert_status=alerts_by_alert_status,
        executions_by_status=executions_by_status,
        recent_alerts=recent_alerts or 0,
    )

#!/usr/bin/env python3
"""Health check endpoint for Bakery."""

import os
import socket
from datetime import datetime, timezone
from typing import Dict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from bakery import __version__
from bakery.config import settings
from bakery.database import get_db
from bakery.schemas import HealthResponse, ComponentHealth

router = APIRouter()


def check_database(db: Session) -> ComponentHealth:
    """
    Check database connectivity.

    Args:
        db: Database session

    Returns:
        ComponentHealth with status
    """
    try:
        # Simple query to verify database is accessible
        db.execute("SELECT 1")
        return ComponentHealth(status="healthy", message="Database accessible")
    except Exception as e:
        return ComponentHealth(
            status="unhealthy",
            message="Database connection failed",
            details={"error": str(e)},
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Returns the health status of Bakery and its dependencies. "
        "Used by Kubernetes liveness and readiness probes."
    ),
)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Health check endpoint."""
    components: Dict[str, ComponentHealth] = {}

    # Check database
    components["database"] = check_database(db)

    # Determine overall status
    component_statuses = [comp.status for comp in components.values()]
    if all(status == "healthy" for status in component_statuses):
        overall_status = "healthy"
    elif any(status == "unhealthy" for status in component_statuses):
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        version=__version__,
        instance_id=os.getenv("HOSTNAME", "unknown"),
        timestamp=datetime.now(timezone.utc),
        components=components,
    )

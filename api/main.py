"""Main FastAPI application - Merged PoundCake."""

from contextlib import asynccontextmanager

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.core.config import settings
from api.core.metrics import init_app_info
from api.core.logging import setup_logging, get_logger
from api.core.middleware import PreHeatMiddleware
from api.core.database import init_db
from api.api import routes, health, recipes, stackstorm, prometheus
from api.api.auth import (
    create_session,
    destroy_session,
    require_auth_if_enabled,
    verify_credentials,
)

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize Prometheus metrics
    if settings.metrics_enabled:
        init_app_info(settings.app_name, settings.app_version)
        logger.info("Prometheus metrics initialized")

    # Initialize database tables
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise

    yield

    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="PoundCake - Alertmanager webhook processing with StackStorm integration",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Add Request ID middleware (pre_heat function)
app.add_middleware(PreHeatMiddleware)

# Include API routers
app.include_router(routes.router, prefix="/api/v1", tags=["alerts"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(recipes.router, tags=["recipes"])
app.include_router(stackstorm.router, tags=["stackstorm"])
app.include_router(prometheus.router, tags=["prometheus"])


# =============================================================================
# Authentication Endpoints
# =============================================================================


@app.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission."""
    if verify_credentials(username, password):
        session_token = create_session(username)
        response = JSONResponse(content={"status": "success", "redirect": "/"})
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            samesite="lax",
            max_age=settings.auth_session_timeout,
        )
        return response
    else:
        return JSONResponse(status_code=401, content={"detail": "Invalid username or password"})


@app.post("/api/logout")
async def logout(session: str | None = Cookie(default=None)):
    """Handle logout."""
    destroy_session(session)
    response = JSONResponse(content={"status": "success", "redirect": "/login"})
    response.delete_cookie(key="session")
    return response


# =============================================================================
# Root Endpoint
# =============================================================================


@app.get("/")
async def root():
    """Root endpoint - returns API info."""
    return JSONResponse(
        {
            "app": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs" if settings.debug else None,
            "health": "/health",
        }
    )


# =============================================================================
# Settings Endpoint
# =============================================================================


@app.get("/api/settings")
async def get_settings_endpoint(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Get non-sensitive application settings for UI display."""
    return {
        "git_enabled": settings.git_enabled,
        "git_provider": settings.git_provider if settings.git_enabled else None,
        "git_repo_url": settings.git_repo_url if settings.git_enabled else None,
        "git_branch": settings.git_branch if settings.git_enabled else None,
        "prometheus_use_crds": settings.prometheus_use_crds,
        "prometheus_crd_namespace": settings.prometheus_crd_namespace,
        "stackstorm_url": settings.stackstorm_url,
        "auth_enabled": settings.auth_enabled,
        "metrics_enabled": settings.metrics_enabled,
    }


# =============================================================================
# Metrics Endpoint
# =============================================================================


@app.get("/metrics")
async def metrics():
    """Expose Prometheus metrics.

    Returns metrics in Prometheus exposition format.
    This endpoint is typically scraped by Prometheus.
    """
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# Legacy Endpoint Aliases (for UI compatibility)
# =============================================================================


@app.get("/health")
async def legacy_health():
    """Legacy health endpoint alias."""
    return await health.health_check()


@app.get("/ready")
async def legacy_ready():
    """Legacy ready endpoint alias."""
    return await health.ready_check()


@app.get("/alerts")
async def legacy_alerts(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Legacy alerts endpoint for UI compatibility.

    Returns alerts in the format expected by the poundcake UI.
    """
    from sqlalchemy.orm import Session
    from api.core.database import get_db
    from api.models.models import Alert, ST2ExecutionLink

    db: Session = next(get_db())
    try:
        query = db.query(Alert)
        if status:
            query = query.filter(Alert.processing_status == status)
        alerts = query.order_by(Alert.created_at.desc()).limit(limit).all()

        # Format for UI compatibility
        result = []
        for alert in alerts:
            # Count executions
            exec_count = (
                db.query(ST2ExecutionLink).filter(ST2ExecutionLink.alert_id == alert.id).count()
            )

            result.append(
                {
                    "fingerprint": alert.fingerprint,
                    "alertname": alert.alert_name,
                    "instance": alert.instance,
                    "severity": alert.severity,
                    "status": alert.processing_status,
                    "received_at": alert.created_at.isoformat() if alert.created_at else None,
                    "total_attempts": exec_count,
                    "successful_attempts": (
                        exec_count if alert.processing_status == "completed" else 0
                    ),
                    "failed_attempts": exec_count if alert.processing_status == "failed" else 0,
                }
            )

        return {"alerts": result}
    finally:
        db.close()


@app.get("/alerts/stats")
async def legacy_alerts_stats(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Legacy alert stats endpoint for UI dashboard."""
    from sqlalchemy import func
    from sqlalchemy.orm import Session
    from api.core.database import get_db
    from api.models.models import Alert

    db: Session = next(get_db())
    try:
        total = db.query(Alert).count()

        # Group by processing status
        status_counts = (
            db.query(Alert.processing_status, func.count(Alert.id))
            .group_by(Alert.processing_status)
            .all()
        )

        by_status = {status: count for status, count in status_counts}

        # Group by severity
        severity_counts = (
            db.query(Alert.severity, func.count(Alert.id)).group_by(Alert.severity).all()
        )

        by_severity = {sev or "unknown": count for sev, count in severity_counts}

        return {
            "total": total,
            "by_status": by_status,
            "by_severity": by_severity,
        }
    finally:
        db.close()


@app.get("/alerts/{fingerprint}")
async def legacy_alert_detail(
    fingerprint: str,
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Legacy single alert endpoint for UI."""
    from sqlalchemy.orm import Session
    from api.core.database import get_db
    from api.models.models import Alert, ST2ExecutionLink

    db: Session = next(get_db())
    try:
        alert = db.query(Alert).filter(Alert.fingerprint == fingerprint).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        # Get execution history
        executions = db.query(ST2ExecutionLink).filter(ST2ExecutionLink.alert_id == alert.id).all()

        remediation_attempts = [
            {
                "action_name": exec.st2_action_ref or "unknown",
                "stackstorm_action": exec.st2_action_ref,
                "status": "success" if alert.processing_status == "completed" else "failed",
                "started_at": exec.created_at.isoformat() if exec.created_at else None,
                "execution_id": exec.st2_execution_id,
                "error": alert.error_message,
            }
            for exec in executions
        ]

        return {
            "alert": {
                "fingerprint": alert.fingerprint,
                "alertname": alert.alert_name,
                "instance": alert.instance,
                "severity": alert.severity,
                "status": alert.processing_status,
                "received_at": alert.created_at.isoformat() if alert.created_at else None,
                "labels": alert.labels,
                "annotations": alert.annotations,
                "remediation_attempts": remediation_attempts,
            }
        }
    finally:
        db.close()


@app.get("/remediations")
async def legacy_remediations(
    request: Request,
    limit: int = 50,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Legacy remediations endpoint for execution history."""
    from sqlalchemy.orm import Session
    from api.core.database import get_db
    from api.models.models import Alert, ST2ExecutionLink

    db: Session = next(get_db())
    try:
        # Get recent executions with alert info
        executions = (
            db.query(ST2ExecutionLink)
            .order_by(ST2ExecutionLink.created_at.desc())
            .limit(limit)
            .all()
        )

        result = []
        for exec in executions:
            alert = db.query(Alert).filter(Alert.id == exec.alert_id).first()
            result.append(
                {
                    "alert_name": alert.alert_name if alert else "unknown",
                    "action_name": exec.st2_action_ref or "unknown",
                    "status": (
                        "success"
                        if (alert and alert.processing_status == "completed")
                        else "running"
                    ),
                    "started_at": exec.created_at.isoformat() if exec.created_at else None,
                    "execution_id": exec.st2_execution_id,
                    "error": alert.error_message if alert else None,
                }
            )

        return {"remediations": result}
    finally:
        db.close()


@app.get("/handlers")
async def legacy_handlers(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
):
    """Legacy handlers endpoint.

    Returns empty list as handlers are now managed via mappings/StackStorm.
    """
    return {"handlers": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        workers=settings.workers if not settings.debug else 1,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )

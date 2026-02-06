#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Health check and statistics endpoints."""

import os
import socket
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session
import httpx

from api.core.database import get_db
from api.core.config import get_settings
from api.schemas.schemas import HealthResponse, ComponentHealth, StatsResponse
from api.models.models import Alert, Recipe, Oven
from api.services.stackstorm_service import get_stackstorm_client
from api.core.logging import get_logger

router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)
SYSTEM_REQ_ID = "SYSTEM-HEALTH"


async def check_mongodb() -> ComponentHealth:
    """Check MongoDB connection."""
    if not settings.mongodb_enabled or settings.mongodb_external:
        return ComponentHealth(status="healthy", message="External or disabled")

    try:
        # Try to connect to MongoDB
        mongodb_host = os.getenv("MONGODB_HOST", "poundcake-mongodb")
        mongodb_port = int(os.getenv("MONGODB_PORT", "27017"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((mongodb_host, mongodb_port))
        sock.close()

        if result == 0:
            return ComponentHealth(status="healthy", message="Connected")
        else:
            return ComponentHealth(status="unhealthy", message="Cannot connect to port")
    except Exception as e:
        return ComponentHealth(status="unhealthy", message=str(e))


async def check_rabbitmq() -> ComponentHealth:
    """Check RabbitMQ connection."""
    if not settings.rabbitmq_enabled:
        return ComponentHealth(status="healthy", message="External or disabled")

    try:
        rabbitmq_host = os.getenv("RABBITMQ_HOST", "poundcake-rabbitmq")
        rabbitmq_port = int(os.getenv("RABBITMQ_MANAGEMENT_PORT", "15672"))

        # Try management API
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(
                f"http://{rabbitmq_host}:{rabbitmq_port}/api/healthchecks/node",
                auth=("guest", "guest"),
            )
            if response.status_code == 200:
                return ComponentHealth(status="healthy", message="Management API accessible")
            else:
                return ComponentHealth(status="degraded", message=f"HTTP {response.status_code}")
    except Exception:
        # Fall back to TCP check
        try:
            rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((rabbitmq_host, rabbitmq_port))
            sock.close()

            if result == 0:
                return ComponentHealth(status="healthy", message="AMQP port accessible")
            else:
                return ComponentHealth(status="unhealthy", message="Cannot connect")
        except Exception as e2:
            return ComponentHealth(status="unhealthy", message=str(e2))


async def check_redis() -> ComponentHealth:
    """Check Redis connection."""
    if not settings.redis_enabled:
        return ComponentHealth(status="healthy", message="External or disabled")

    try:
        redis_host = os.getenv("REDIS_HOST", "poundcake-redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((redis_host, redis_port))
        sock.close()

        if result == 0:
            return ComponentHealth(status="healthy", message="Connected")
        else:
            return ComponentHealth(status="unhealthy", message="Cannot connect")
    except Exception as e:
        return ComponentHealth(status="unhealthy", message=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Comprehensive health check for all PoundCake components."""
    components = {}

    # Check MariaDB/MySQL Database
    try:
        db.execute(text("SELECT 1"))
        components["database"] = ComponentHealth(status="healthy", message="Connected")
    except Exception as e:
        components["database"] = ComponentHealth(status="unhealthy", message=str(e))

    # Check StackStorm
    try:
        st2_client = get_stackstorm_client()
        is_st2_healthy = await st2_client.health_check(req_id=SYSTEM_REQ_ID)
        if is_st2_healthy:
            components["stackstorm"] = ComponentHealth(status="healthy", message="API accessible")
        else:
            components["stackstorm"] = ComponentHealth(
                status="unhealthy", message="API not responding"
            )
    except Exception as e:
        components["stackstorm"] = ComponentHealth(status="unhealthy", message=str(e))

    # Check MongoDB (used by StackStorm)
    components["mongodb"] = await check_mongodb()

    # Check RabbitMQ (used by StackStorm)
    components["rabbitmq"] = await check_rabbitmq()

    # Check Redis (used by StackStorm for coordination)
    components["redis"] = await check_redis()

    # Determine overall status
    unhealthy_count = sum(1 for c in components.values() if c.status == "unhealthy")
    degraded_count = sum(1 for c in components.values() if c.status == "degraded")

    if unhealthy_count > 0:
        overall_status = "unhealthy"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # Get instance ID (pod name in Kubernetes, hostname otherwise)
    instance_id = os.getenv("HOSTNAME", socket.gethostname())

    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        instance_id=instance_id,
        timestamp=datetime.now(timezone.utc),
        components=components,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_statistics(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    """System statistics with mapped model fields."""
    result = await db.execute(select(func.count(Alert.id)))
    total_alerts = result.scalar() or 0
    result = await db.execute(select(func.count(Recipe.id)))
    total_recipes = result.scalar() or 0
    result = await db.execute(select(func.count(Oven.id)))
    total_executions = result.scalar() or 0

    # Grouping queries
    result = await db.execute(
        select(Alert.processing_status, func.count(Alert.id)).group_by(Alert.processing_status)
    )
    alerts_by_status = dict(result.all())

    # Mapping Alert.alert_status (firing/resolved)
    result = await db.execute(
        select(Alert.alert_status, func.count(Alert.id)).group_by(Alert.alert_status)
    )
    alerts_by_alert = dict(result.all())

    # Mapping Oven.processing_status
    result = await db.execute(
        select(Oven.processing_status, func.count(Oven.id)).group_by(Oven.processing_status)
    )
    executions_by_status = dict(result.all())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(select(func.count(Alert.id)).where(Alert.created_at >= cutoff))
    recent = result.scalar() or 0

    return StatsResponse(
        total_alerts=total_alerts,
        total_recipes=total_recipes,
        total_executions=total_executions,
        alerts_by_processing_status=alerts_by_status,
        alerts_by_alert_status=alerts_by_alert,
        executions_by_status=executions_by_status,
        recent_alerts=recent,
    )

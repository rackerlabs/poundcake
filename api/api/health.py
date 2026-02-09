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
from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, text, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.config import get_settings
from api.core.http_client import request_with_retry
from api.schemas.schemas import HealthResponse, ComponentHealth, StatsResponse
from api.models.models import Order, Recipe, Dish
from api.services.stackstorm_service import get_stackstorm_client
from api.core.logging import get_logger

router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)
SYSTEM_REQ_ID = "SYSTEM-HEALTH"
BOOTSTRAP_DONE_FILE = "/tmp/poundcake_bootstrap.done"


async def check_mongodb() -> ComponentHealth:
    """Check MongoDB connection."""
    if not settings.mongodb_enabled or settings.mongodb_external:
        return ComponentHealth(status="healthy", message="External or disabled")

    try:
        # Try to connect to MongoDB
        mongodb_host = os.getenv("MONGODB_HOST", "stackstorm-mongodb")
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
        rabbitmq_host = os.getenv("RABBITMQ_HOST", "stackstorm-rabbitmq")
        rabbitmq_port = int(os.getenv("RABBITMQ_MANAGEMENT_PORT", "15672"))
        rabbitmq_user = os.getenv("RABBITMQ_USER", "stackstorm")
        rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "password")

        # Try management API
        response = await request_with_retry(
            "GET",
            f"http://{rabbitmq_host}:{rabbitmq_port}/api/healthchecks/node",
            auth=(rabbitmq_user, rabbitmq_password),
            timeout=2.0,
            retries=0,
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
        redis_host = os.getenv("REDIS_HOST", "stackstorm-redis")
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
async def health_check(response: Response, db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Comprehensive health check for all PoundCake components."""
    components = {}

    # Check MariaDB/MySQL Database
    try:
        await db.execute(text("SELECT 1"))
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

    # Check PoundCake bootstrap completion
    if os.path.exists(BOOTSTRAP_DONE_FILE):
        components["poundcake_bootstrap"] = ComponentHealth(
            status="healthy", message="Bootstrap completed"
        )
    else:
        components["poundcake_bootstrap"] = ComponentHealth(
            status="unhealthy", message="Bootstrap not completed"
        )

    # Determine overall status
    unhealthy_count = sum(1 for c in components.values() if c.status == "unhealthy")
    degraded_count = sum(1 for c in components.values() if c.status == "degraded")

    if unhealthy_count > 0:
        overall_status = "unhealthy"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    if overall_status != "healthy":
        response.status_code = 503

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
    result = await db.execute(select(func.count(Order.id)))
    total_orders = result.scalar() or 0
    result = await db.execute(select(func.count(Recipe.id)))
    total_recipes = result.scalar() or 0
    result = await db.execute(select(func.count(Dish.id)))
    total_dishes = result.scalar() or 0

    result = await db.execute(
        select(Order.processing_status, func.count(Order.id)).group_by(Order.processing_status)
    )
    orders_by_status = dict(result.all())

    result = await db.execute(
        select(Order.alert_status, func.count(Order.id)).group_by(Order.alert_status)
    )
    orders_by_alert = dict(result.all())

    result = await db.execute(
        select(Dish.processing_status, func.count(Dish.id)).group_by(Dish.processing_status)
    )
    dishes_by_status = dict(result.all())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(select(func.count(Order.id)).where(Order.created_at >= cutoff))
    recent = result.scalar() or 0

    return StatsResponse(
        total_orders=total_orders,
        total_recipes=total_recipes,
        total_dishes=total_dishes,
        orders_by_processing_status=orders_by_status,
        orders_by_alert_status=orders_by_alert,
        dishes_by_status=dishes_by_status,
        recent_orders=recent,
    )

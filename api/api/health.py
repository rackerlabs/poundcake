#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Health check and statistics endpoints."""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func, text, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.config import get_settings
from api.schemas.schemas import HealthResponse, StatsResponse
from api.models.models import Alert, Recipe, Oven
from api.services.stackstorm_service import get_stackstorm_client

router = APIRouter()
settings = get_settings()
SYSTEM_REQ_ID = "SYSTEM-HEALTH"


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Health check using the existing StackStorm client health_check method."""
    # Check Database
    try:
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Check StackStorm via existing async client
    st2_client = get_stackstorm_client()
    is_st2_healthy = await st2_client.health_check(req_id=SYSTEM_REQ_ID)
    st2_status = "healthy" if is_st2_healthy else "unhealthy"

    overall_status = "healthy" if db_status == "healthy" and is_st2_healthy else "degraded"

    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_status,
        stackstorm=st2_status,
        timestamp=datetime.now(timezone.utc),
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

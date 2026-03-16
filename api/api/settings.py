#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Settings API endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.config import get_settings
from api.core.logging import get_logger
from api.api.auth import require_auth_if_enabled
from api.services.communications_policy import global_policy_configured
from contracts.poundcake import AppSettingsResponse

logger = get_logger(__name__)
router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=AppSettingsResponse)
async def get_application_settings(
    request: Request,
    _user: str | None = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
) -> AppSettingsResponse:
    """Get application settings for UI configuration.

    Returns settings that the UI needs to configure itself properly.
    """
    settings = get_settings()
    req_id = request.state.req_id

    logger.debug("Settings requested", extra={"req_id": req_id})

    communications_configured = await global_policy_configured(db)

    return AppSettingsResponse(
        auth_enabled=settings.auth_enabled,
        prometheus_use_crds=settings.prometheus_use_crds,
        prometheus_crd_namespace=settings.prometheus_crd_namespace,
        prometheus_url=settings.prometheus_url,
        git_enabled=settings.git_enabled,
        git_provider=settings.git_provider if settings.git_enabled else None,
        stackstorm_enabled=True,
        version=settings.app_version,
        global_communications_configured=communications_configured,
    )

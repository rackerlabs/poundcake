#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Internal StackStorm helper endpoints for in-cluster pack sync."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.logging import get_logger
from api.core.metrics import record_deprecated_endpoint_hit
from api.services.pack_sync_service import get_pack_sync_artifact_response

logger = get_logger(__name__)

router = APIRouter()


@router.get("/internal/stackstorm/pack.tgz")
async def get_stackstorm_pack_tgz(
    request: Request,
    db: AsyncSession = Depends(get_db),
    pack_sync_token: str | None = Header(default=None, alias="X-Pack-Sync-Token"),
):
    """Deprecated pack-sync endpoint kept for migration compatibility."""
    logger.warning(
        "Deprecated pack-sync endpoint called",
        extra={
            "event": "endpoint_deprecated",
            "deprecated_endpoint": "/api/v1/internal/stackstorm/pack.tgz",
            "replacement_endpoint": "/api/v1/cook/packs",
        },
    )
    record_deprecated_endpoint_hit(
        endpoint="/api/v1/internal/stackstorm/pack.tgz",
        replacement="/api/v1/cook/packs",
    )
    return await get_pack_sync_artifact_response(
        request=request,
        db=db,
        pack_sync_token=pack_sync_token,
    )

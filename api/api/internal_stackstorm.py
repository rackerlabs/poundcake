#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Internal StackStorm helper endpoints for in-cluster pack sync."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.config import get_settings
from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Recipe, RecipeIngredient
from api.services.stackstorm_service import build_stackstorm_pack_artifact

logger = get_logger(__name__)

router = APIRouter()


@router.get("/internal/stackstorm/pack.tgz")
async def get_stackstorm_pack_tgz(
    request: Request,
    db: AsyncSession = Depends(get_db),
    pack_sync_token: str | None = Header(default=None, alias="X-Pack-Sync-Token"),
):
    """Return the current generated PoundCake StackStorm pack as tar.gz."""
    settings = get_settings()
    expected_token = settings.pack_sync_token

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pack sync endpoint is not configured",
        )

    if not pack_sync_token or not secrets.compare_digest(pack_sync_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid pack sync token",
        )

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.deleted.is_(False))
        .where(Recipe.enabled.is_(True))
        .where(Recipe.source_type == "stackstorm")
    )
    recipes = result.unique().scalars().all()
    artifact_bytes, etag = build_stackstorm_pack_artifact(recipes=recipes)

    headers = {"ETag": etag, "Cache-Control": "no-cache"}

    request_etag = request.headers.get("if-none-match", "").strip()
    if request_etag == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return Response(content=artifact_bytes, media_type="application/gzip", headers=headers)

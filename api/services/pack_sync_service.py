#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Shared helpers for PoundCake StackStorm pack-sync endpoints."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.config import get_settings
from api.models.models import Recipe, RecipeIngredient
from api.services.stackstorm_service import build_stackstorm_pack_artifact


def _validate_pack_sync_token(pack_sync_token: str | None) -> None:
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


async def get_pack_sync_artifact_response(
    request: Request,
    db: AsyncSession,
    pack_sync_token: str | None,
) -> Response:
    """Return pack artifact payload response for pack-sync endpoints."""
    _validate_pack_sync_token(pack_sync_token)

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

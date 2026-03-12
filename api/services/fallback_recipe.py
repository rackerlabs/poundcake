"""Fallback recipe provisioning helpers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.models.models import Recipe
from api.services.communications_policy import get_global_policy_routes, sync_fallback_policy_recipe

logger = get_logger(__name__)


async def ensure_fallback_recipe(
    db: AsyncSession,
    *,
    req_id: str,
) -> Recipe | None:
    """Ensure fallback recipe matches the effective global communications policy."""
    routes = await get_global_policy_routes(db)
    recipe = await sync_fallback_policy_recipe(db, routes=routes)
    logger.info(
        "Ensured fallback recipe from communications policy",
        extra={
            "req_id": req_id,
            "recipe_name": recipe.name if recipe is not None else None,
            "recipe_id": recipe.id if recipe is not None else None,
            "route_count": len(routes),
        },
    )
    return recipe

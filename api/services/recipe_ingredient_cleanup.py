"""Helpers for safely replacing recipe_ingredients."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.models import DishIngredient, RecipeIngredient


async def delete_recipe_ingredients_safely(db: AsyncSession, *, recipe_id: int) -> None:
    """Detach historical dish rows before deleting recipe step definitions."""
    recipe_ingredient_ids = select(RecipeIngredient.id).where(
        RecipeIngredient.recipe_id == recipe_id
    )

    await db.execute(
        update(DishIngredient)
        .where(DishIngredient.recipe_ingredient_id.in_(recipe_ingredient_ids))
        .values(
            recipe_ingredient_id=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id))

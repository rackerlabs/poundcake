"""Helpers for safely replacing recipe_ingredients."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.models import DishIngredient, RecipeIngredient


def _detach_task_key(
    *,
    dish_id: int,
    row_id: int,
    task_key: str | None,
    occupied_task_keys: dict[int, set[str]],
) -> str | None:
    normalized = task_key or ""
    if normalized not in occupied_task_keys[dish_id]:
        occupied_task_keys[dish_id].add(normalized)
        return task_key

    base = str(task_key or "detached-step").strip() or "detached-step"
    candidate = f"{base}::detached::{row_id}"
    occupied_task_keys[dish_id].add(candidate)
    return candidate


async def detach_recipe_ingredient_ids_safely(
    db: AsyncSession, *, recipe_ingredient_ids: Iterable[int]
) -> None:
    """Detach dish rows without violating the `(dish_id, recipe_step, task_key)` uniqueness key."""
    ids = [int(recipe_ingredient_id) for recipe_ingredient_id in recipe_ingredient_ids]
    if not ids:
        return

    result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.recipe_ingredient_id.in_(ids))
        .order_by(
            DishIngredient.dish_id, DishIngredient.updated_at.desc(), DishIngredient.id.desc()
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return

    selected_ids = {int(row.id) for row in rows}
    affected_dish_ids = sorted({int(row.dish_id) for row in rows})
    occupancy_result = await db.execute(
        select(
            DishIngredient.id,
            DishIngredient.dish_id,
            DishIngredient.recipe_ingredient_id,
            DishIngredient.task_key,
        ).where(DishIngredient.dish_id.in_(affected_dish_ids))
    )
    occupied_task_keys: dict[int, set[str]] = defaultdict(set)
    for row_id, dish_id, recipe_ingredient_id, task_key in occupancy_result.all():
        if int(row_id) in selected_ids:
            continue
        if recipe_ingredient_id is None:
            occupied_task_keys[int(dish_id)].add(task_key or "")

    now = datetime.now(timezone.utc)
    for row in rows:
        row.recipe_ingredient_id = None
        row.task_key = _detach_task_key(
            dish_id=int(row.dish_id),
            row_id=int(row.id),
            task_key=row.task_key,
            occupied_task_keys=occupied_task_keys,
        )
        row.updated_at = now

    await db.flush()


async def delete_recipe_ingredients_safely(db: AsyncSession, *, recipe_id: int) -> None:
    """Detach historical dish rows before deleting recipe step definitions."""
    result = await db.execute(
        select(RecipeIngredient.id).where(RecipeIngredient.recipe_id == recipe_id)
    )
    recipe_ingredient_ids = [
        int(recipe_ingredient_id) for recipe_ingredient_id in result.scalars().all()
    ]
    await detach_recipe_ingredient_ids_safely(db, recipe_ingredient_ids=recipe_ingredient_ids)
    await db.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id))

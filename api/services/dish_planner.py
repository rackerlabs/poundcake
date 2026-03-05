"""Shared planning helpers for phase-scoped dish dispatch."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.models import DishIngredient, Ingredient, Recipe, RecipeIngredient


def is_phase_eligible(step_phase: str | None, target_phase: str) -> bool:
    normalized = (step_phase or "both").lower()
    return normalized == "both" or normalized == target_phase


def build_step_task_key(ri: RecipeIngredient) -> str:
    task_suffix = ((ri.ingredient.task_key_template if ri.ingredient else None) or "task").replace(
        ".", "_"
    )
    return f"step_{ri.step_order}_{task_suffix}"


def build_step_parameters(ri: RecipeIngredient) -> dict[str, Any] | None:
    base = dict((ri.ingredient.execution_parameters if ri.ingredient else None) or {})
    if ri.execution_parameters_override:
        base.update(ri.execution_parameters_override)
    return base or None


async def expected_duration_for_phase(db: AsyncSession, *, recipe_id: int, phase: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(Ingredient.expected_duration_sec), 0))
        .select_from(RecipeIngredient)
        .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
        .where(
            RecipeIngredient.recipe_id == recipe_id,
            RecipeIngredient.run_phase.in_((phase, "both")),
        )
    )
    return int(result.scalar() or 0)


def seed_dish_ingredients_for_phase(
    *,
    dish_id: int,
    recipe: Recipe,
    phase: str,
    existing_by_recipe_ingredient_id: dict[int, DishIngredient] | None = None,
) -> list[DishIngredient]:
    existing = existing_by_recipe_ingredient_id or {}
    seeded: list[DishIngredient] = []
    for ri in recipe.recipe_ingredients:
        if ri.ingredient is None:
            continue
        if not is_phase_eligible(ri.run_phase, phase):
            continue
        if ri.id in existing:
            continue

        seeded.append(
            DishIngredient(
                dish_id=dish_id,
                recipe_ingredient_id=ri.id,
                task_key=build_step_task_key(ri),
                execution_engine=ri.ingredient.execution_engine,
                execution_target=ri.ingredient.execution_target,
                execution_payload=ri.ingredient.execution_payload,
                execution_parameters=build_step_parameters(ri),
                execution_status="pending",
            )
        )
    return seeded

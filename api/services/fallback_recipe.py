"""Fallback recipe provisioning helpers."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient

logger = get_logger(__name__)


async def _await_if_needed(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def ensure_fallback_recipe(
    db: AsyncSession,
    *,
    req_id: str,
) -> Recipe | None:
    """Ensure fallback recipe and its default bakery ingredient exist."""
    settings = get_settings()
    recipe_name = (settings.catch_all_recipe_name or "").strip()
    if not recipe_name:
        return None

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Ingredient)
        .where(Ingredient.execution_engine == "bakery", Ingredient.execution_target == "core")
        .with_for_update()
    )
    ingredient_scalars = await _await_if_needed(result.scalars())
    ingredient = await _await_if_needed(ingredient_scalars.first())
    if ingredient is None:
        ingredient = Ingredient(
            execution_target="core",
            task_key_template="core",
            execution_engine="bakery",
            execution_purpose="comms",
            execution_payload={"template": {"context": {"source": "poundcake"}}},
            execution_parameters={"operation": "ticket_update"},
            is_default=True,
            is_blocking=False,
            expected_duration_sec=15,
            timeout_duration_sec=120,
            retry_count=1,
            retry_delay=5,
            on_failure="continue",
            deleted=False,
            deleted_at=None,
            updated_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(ingredient)
                await db.flush()
        except IntegrityError:
            # Concurrent create won this race; re-read the row and continue.
            retry_result = await db.execute(
                select(Ingredient)
                .where(
                    Ingredient.execution_engine == "bakery", Ingredient.execution_target == "core"
                )
                .with_for_update()
            )
            retry_scalars = await _await_if_needed(retry_result.scalars())
            ingredient = await _await_if_needed(retry_scalars.first())
            if ingredient is None:
                raise

    changed = False
    if ingredient.is_default is False:
        ingredient.is_default = True
        changed = True
    if ingredient.deleted or ingredient.deleted_at is not None:
        ingredient.deleted = False
        ingredient.deleted_at = None
        changed = True
    if changed:
        ingredient.updated_at = now

    recipe_result = await db.execute(
        select(Recipe)
        .where(Recipe.name == recipe_name)
        .with_for_update()
    )
    unique_recipe_result = await _await_if_needed(recipe_result.unique())
    recipe_scalars = await _await_if_needed(unique_recipe_result.scalars())
    recipe = await _await_if_needed(recipe_scalars.first())
    if recipe is None:
        recipe = Recipe(
            name=recipe_name,
            description="Fallback recipe for unmatched alerts",
            enabled=True,
            deleted=False,
            deleted_at=None,
            updated_at=now,
        )
        db.add(recipe)
        await db.flush()
    else:
        changed = False
        if recipe.enabled is False:
            recipe.enabled = True
            changed = True
        if recipe.deleted or recipe.deleted_at is not None:
            recipe.deleted = False
            recipe.deleted_at = None
            changed = True
        if changed:
            recipe.updated_at = now

    step_result = await db.execute(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe.id, RecipeIngredient.step_order == 1)
        .with_for_update()
    )
    step_scalars = await _await_if_needed(step_result.scalars())
    existing_step = await _await_if_needed(step_scalars.first())
    if existing_step is None:
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                step_order=1,
                on_success="continue",
                parallel_group=0,
                depth=0,
                run_phase="resolving",
                execution_parameters_override=None,
            )
        )
    else:
        changed = False
        if existing_step.ingredient_id != ingredient.id:
            existing_step.ingredient_id = ingredient.id
            changed = True
        if existing_step.run_phase != "resolving":
            existing_step.run_phase = "resolving"
            changed = True
        if existing_step.on_success != "continue":
            existing_step.on_success = "continue"
            changed = True
        if changed:
            logger.info(
                "Updated fallback recipe first step",
                extra={"req_id": req_id, "recipe_name": recipe_name, "recipe_id": recipe.id},
            )

    return recipe

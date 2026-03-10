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
from api.services.communications import DESTINATION_TYPES, normalize_destination_type
from api.services.recipe_ingredient_cleanup import delete_recipe_ingredients_safely

logger = get_logger(__name__)

FALLBACK_OPEN_TASK_KEY = "fallback_open"
FALLBACK_UPDATE_TASK_KEY = "fallback_update"


async def _await_if_needed(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _fallback_destination_type() -> str:
    settings = get_settings()
    selected = normalize_destination_type(settings.bakery_active_provider or "rackspace_core")
    if selected in DESTINATION_TYPES:
        return selected
    return "rackspace_core"


async def _get_or_create_managed_ingredient(
    db: AsyncSession,
    *,
    execution_target: str,
    task_key_template: str,
    execution_payload: dict,
    execution_parameters: dict,
    now: datetime,
) -> Ingredient:
    result = await db.execute(
        select(Ingredient)
        .where(
            Ingredient.execution_engine == "bakery",
            Ingredient.execution_target == execution_target,
            Ingredient.destination_target == "",
            Ingredient.task_key_template == task_key_template,
        )
        .with_for_update()
    )
    scalars = await _await_if_needed(result.scalars())
    ingredient = await _await_if_needed(scalars.first())
    if ingredient is None:
        ingredient = Ingredient(
            execution_target=execution_target,
            destination_target="",
            task_key_template=task_key_template,
            execution_engine="bakery",
            execution_purpose="comms",
            execution_payload=execution_payload,
            execution_parameters=execution_parameters,
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
            retry_result = await db.execute(
                select(Ingredient)
                .where(
                    Ingredient.execution_engine == "bakery",
                    Ingredient.execution_target == execution_target,
                    Ingredient.destination_target == "",
                    Ingredient.task_key_template == task_key_template,
                )
                .with_for_update()
            )
            retry_scalars = await _await_if_needed(retry_result.scalars())
            ingredient = await _await_if_needed(retry_scalars.first())
            if ingredient is None:
                raise
    changed = False
    for field_name, value in (
        ("execution_payload", execution_payload),
        ("execution_parameters", execution_parameters),
        ("execution_purpose", "comms"),
        ("destination_target", ""),
        ("is_default", True),
        ("is_blocking", False),
        ("expected_duration_sec", 15),
        ("timeout_duration_sec", 120),
        ("retry_count", 1),
        ("retry_delay", 5),
        ("on_failure", "continue"),
    ):
        if getattr(ingredient, field_name) != value:
            setattr(ingredient, field_name, value)
            changed = True
    if ingredient.deleted or ingredient.deleted_at is not None:
        ingredient.deleted = False
        ingredient.deleted_at = None
        changed = True
    if changed:
        ingredient.updated_at = now
    return ingredient


async def ensure_fallback_recipe(
    db: AsyncSession,
    *,
    req_id: str,
) -> Recipe | None:
    """Ensure fallback recipe and its managed comms ingredients exist."""
    settings = get_settings()
    recipe_name = (settings.catch_all_recipe_name or "").strip()
    if not recipe_name:
        return None

    now = datetime.now(timezone.utc)
    execution_target = _fallback_destination_type()
    open_ingredient = await _get_or_create_managed_ingredient(
        db,
        execution_target=execution_target,
        task_key_template=FALLBACK_OPEN_TASK_KEY,
        execution_payload={
            "title": "Alert active - manual action required",
            "description": (
                "PoundCake did not find an auto-remediation recipe for this alert. "
                "Manual investigation is required."
            ),
            "message": "Alert active. No auto-remediation is defined. Manual action required.",
            "source": "poundcake",
            "context": {
                "source": "poundcake",
                "communication_reason": "no_remediation",
            },
        },
        execution_parameters={"operation": "open"},
        now=now,
    )
    update_ingredient = await _get_or_create_managed_ingredient(
        db,
        execution_target=execution_target,
        task_key_template=FALLBACK_UPDATE_TASK_KEY,
        execution_payload={
            "description": "Alert cleared after manual or external action.",
            "comment": "Alert cleared. Leaving communication open for the human responder.",
            "message": "Alert cleared. Communication remains open for manual ownership.",
            "context": {
                "source": "poundcake",
                "communication_reason": "no_remediation_cleared",
            },
        },
        execution_parameters={"operation": "update"},
        now=now,
    )

    recipe_result = await db.execute(
        select(Recipe).where(Recipe.name == recipe_name).with_for_update()
    )
    recipe_scalars = await _await_if_needed(recipe_result.scalars())
    recipe = await _await_if_needed(recipe_scalars.first())
    if recipe is None:
        recipe = Recipe(
            name=recipe_name,
            description="Fallback recipe for unmatched alerts",
            enabled=True,
            clear_timeout_sec=None,
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
        if recipe.description != "Fallback recipe for unmatched alerts":
            recipe.description = "Fallback recipe for unmatched alerts"
            changed = True
        if recipe.deleted or recipe.deleted_at is not None:
            recipe.deleted = False
            recipe.deleted_at = None
            changed = True
        if changed:
            recipe.updated_at = now

    await delete_recipe_ingredients_safely(db, recipe_id=recipe.id)
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=open_ingredient.id,
            step_order=1,
            on_success="continue",
            parallel_group=0,
            depth=0,
            run_phase="firing",
            run_condition="always",
            execution_parameters_override=None,
        )
    )
    db.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=update_ingredient.id,
            step_order=2,
            on_success="continue",
            parallel_group=0,
            depth=0,
            run_phase="resolving",
            run_condition="resolved_after_no_remediation",
            execution_parameters_override=None,
        )
    )
    logger.info(
        "Ensured fallback recipe",
        extra={
            "req_id": req_id,
            "recipe_name": recipe_name,
            "recipe_id": recipe.id,
            "execution_target": execution_target,
        },
    )
    return recipe

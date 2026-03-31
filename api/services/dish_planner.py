"""Shared planning helpers for phase-scoped dish dispatch."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.models import DishIngredient, Ingredient, Order, Recipe, RecipeIngredient
from api.services.communications import normalize_run_condition, normalize_run_phase
from api.services.communications_policy import should_seed_route_step


def is_phase_eligible(step_phase: str | None, target_phase: str) -> bool:
    normalized = normalize_run_phase(step_phase)
    target = normalize_run_phase(target_phase)
    if normalized == "both":
        return target in {"firing", "resolving"}
    return normalized == target


def is_non_firing_ingredient_eligible(ri: RecipeIngredient) -> bool:
    """Escalation and resolving phases only execute Bakery comms ingredients."""
    ingredient = ri.ingredient
    if ingredient is None:
        return False
    if (ingredient.execution_engine or "").strip().lower() != "bakery":
        return False
    return (ingredient.execution_purpose or "").strip().lower() == "comms"


def is_run_condition_eligible(ri: RecipeIngredient, *, phase: str, order: Order | None) -> bool:
    condition = normalize_run_condition(getattr(ri, "run_condition", "always"))
    if condition == "always":
        return True
    if order is None:
        return False

    remediation_outcome = str(getattr(order, "remediation_outcome", "") or "").lower()
    timed_out = getattr(order, "clear_timed_out_at", None) is not None
    target_phase = normalize_run_phase(phase)

    if target_phase == "escalation":
        if condition == "remediation_failed":
            return remediation_outcome == "failed"
        if condition == "clear_timeout_expired":
            return timed_out
        return False

    if target_phase == "resolving":
        if condition == "resolved_after_success":
            return remediation_outcome == "succeeded" and not timed_out
        if condition == "resolved_after_failure":
            return remediation_outcome == "failed"
        if condition == "resolved_after_no_remediation":
            return remediation_outcome == "none"
        if condition == "resolved_after_timeout":
            return timed_out
        return False

    return condition == "always"


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


def build_step_payload(ri: RecipeIngredient) -> dict[str, Any] | None:
    base = dict((ri.ingredient.execution_payload if ri.ingredient else None) or {})
    if ri.execution_payload_override:
        base.update(ri.execution_payload_override)
    return base or None


def resolved_expected_duration_sec(ri: RecipeIngredient) -> int | None:
    if ri.expected_duration_sec_override is not None:
        return int(ri.expected_duration_sec_override)
    if ri.ingredient is None or getattr(ri.ingredient, "expected_duration_sec", None) is None:
        return None
    return int(ri.ingredient.expected_duration_sec)


def resolved_timeout_duration_sec(ri: RecipeIngredient) -> int | None:
    if ri.timeout_duration_sec_override is not None:
        return int(ri.timeout_duration_sec_override)
    if ri.ingredient is None or getattr(ri.ingredient, "timeout_duration_sec", None) is None:
        return None
    return int(ri.ingredient.timeout_duration_sec)


async def expected_duration_for_phase(
    db: AsyncSession,
    *,
    recipe_id: int,
    phase: str,
    extra_recipe_ingredients: list[RecipeIngredient] | None = None,
) -> int:
    normalized_phase = normalize_run_phase(phase)
    allowed_phases = (
        (normalized_phase, "both") if normalized_phase != "escalation" else ("escalation",)
    )
    query = (
        select(func.coalesce(func.sum(Ingredient.expected_duration_sec), 0))
        .select_from(RecipeIngredient)
        .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
        .where(
            RecipeIngredient.recipe_id == recipe_id,
            RecipeIngredient.run_phase.in_(allowed_phases),
        )
    )
    if normalized_phase in {"escalation", "resolving"}:
        query = query.where(
            Ingredient.execution_engine == "bakery",
            Ingredient.execution_purpose == "comms",
        )
    result = await db.execute(query)
    total = int(result.scalar() or 0)
    if extra_recipe_ingredients:
        for ri in extra_recipe_ingredients:
            if ri.ingredient is None:
                continue
            if not is_phase_eligible(ri.run_phase, phase):
                continue
            if normalized_phase in {
                "escalation",
                "resolving",
            } and not is_non_firing_ingredient_eligible(ri):
                continue
            total += int(resolved_expected_duration_sec(ri) or 0)
    return total


def seed_dish_ingredients_for_phase(
    *,
    dish_id: int,
    recipe: Recipe,
    phase: str,
    order: Order | None = None,
    existing_by_recipe_ingredient_id: dict[int, DishIngredient] | None = None,
    extra_recipe_ingredients: list[RecipeIngredient] | None = None,
) -> list[DishIngredient]:
    existing = existing_by_recipe_ingredient_id or {}
    seeded: list[DishIngredient] = []
    normalized_phase = normalize_run_phase(phase)
    for ri in list(recipe.recipe_ingredients) + list(extra_recipe_ingredients or []):
        if ri.ingredient is None:
            continue
        if not is_phase_eligible(ri.run_phase, phase):
            continue
        if normalized_phase in {
            "escalation",
            "resolving",
        } and not is_non_firing_ingredient_eligible(ri):
            continue
        if not is_run_condition_eligible(ri, phase=phase, order=order):
            continue
        if not should_seed_route_step(recipe_ingredient=ri, order=order):
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
                destination_target=getattr(ri.ingredient, "destination_target", "") or "",
                execution_payload=build_step_payload(ri),
                execution_parameters=build_step_parameters(ri),
                expected_duration_sec=resolved_expected_duration_sec(ri),
                timeout_duration_sec=resolved_timeout_duration_sec(ri),
                retry_count=getattr(ri.ingredient, "retry_count", None),
                retry_delay=getattr(ri.ingredient, "retry_delay", None),
                on_failure=getattr(ri.ingredient, "on_failure", None),
                execution_status="pending",
            )
        )
    return seeded

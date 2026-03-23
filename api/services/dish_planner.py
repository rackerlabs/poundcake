"""Shared planning helpers for phase-scoped dish dispatch."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.models import DishIngredient, Ingredient, Order, Recipe, RecipeIngredient
from api.services.bakery_payloads import resolve_bakery_payload
from api.services.communication_canonical import build_canonical_communication_context
from api.services.communications import (
    normalize_communication_operation,
    normalize_run_condition,
    normalize_run_phase,
)
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


def build_step_execution_payload(
    *,
    ri: RecipeIngredient,
    order: Order | None = None,
) -> dict[str, Any] | None:
    ingredient = ri.ingredient
    if ingredient is None:
        return None

    payload = ingredient.execution_payload if isinstance(ingredient.execution_payload, dict) else None
    if (ingredient.execution_engine or "").strip().lower() != "bakery":
        return payload
    if (ingredient.execution_purpose or "").strip().lower() != "comms":
        return payload

    destination_target = getattr(ingredient, "destination_target", "") or ""
    parameters = build_step_parameters(ri)
    operation = normalize_communication_operation((parameters or {}).get("operation"))
    runtime_overlay: dict[str, Any] = {
        "context": {
            "provider_type": ingredient.execution_target,
            "destination_target": destination_target,
        }
    }

    resolved = resolve_bakery_payload(payload, runtime_overlay=runtime_overlay)
    resolved_context = (
        dict(resolved.get("context")) if isinstance(resolved.get("context"), dict) else {}
    )
    if order is not None:
        resolved_context["_canonical"] = build_canonical_communication_context(
            order=order,
            execution_target=ingredient.execution_target,
            destination_target=destination_target,
            operation=operation,
            execution_payload={**resolved, "context": resolved_context},
        )
    resolved["context"] = resolved_context
    return resolved


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
            total += int(getattr(ri.ingredient, "expected_duration_sec", 0) or 0)
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
                execution_payload=build_step_execution_payload(ri=ri, order=order),
                execution_parameters=build_step_parameters(ri),
                execution_status="pending",
            )
        )
    return seeded

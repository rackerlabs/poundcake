"""Bootstrap recipe catalog loader/upsert helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.services.communications import (
    RUN_CONDITIONS,
    RUN_PHASES,
    normalize_destination_target,
    normalize_destination_type,
    normalize_run_condition,
)
from api.services.recipe_ingredient_cleanup import delete_recipe_ingredients_safely

logger = get_logger(__name__)

CATALOG_API_VERSION = "poundcake/v1"
CATALOG_KIND = "RecipeCatalogEntry"
VALID_RUN_PHASES = RUN_PHASES
VALID_ON_SUCCESS = {"continue", "stop"}


def _is_managed_bootstrap_recipe_description(description: str | None) -> bool:
    if not isinstance(description, str):
        return False
    return description.startswith(
        "Bootstrap-managed remote recipe for alert rule"
    ) or description.startswith("Bootstrap-generated recipe for alert group ")


def load_bootstrap_recipe_catalog(
    recipes_dir: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load and validate bootstrap recipe catalog entries from a directory."""
    errors: list[str] = []
    entries: list[dict[str, Any]] = []

    base = Path(recipes_dir)
    if not base.exists():
        return [], [f"recipe catalog directory not found: {recipes_dir}"]
    if not base.is_dir():
        return [], [f"recipe catalog path is not a directory: {recipes_dir}"]

    for path in sorted(base.glob("*.yaml")):
        payload, file_errors = _load_recipe_entry(path)
        if file_errors:
            errors.extend(file_errors)
            continue
        entries.append(payload)
    return entries, errors


def _load_recipe_entry(path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return {}, [f"{path.name}: failed to parse yaml: {exc}"]

    if not isinstance(raw, dict):
        return {}, [f"{path.name}: root must be an object"]

    if raw.get("apiVersion") != CATALOG_API_VERSION:
        errors.append(
            f"{path.name}: apiVersion must be '{CATALOG_API_VERSION}', got '{raw.get('apiVersion')}'"
        )
    if raw.get("kind") != CATALOG_KIND:
        errors.append(f"{path.name}: kind must be '{CATALOG_KIND}', got '{raw.get('kind')}'")

    recipe = raw.get("recipe")
    if not isinstance(recipe, dict):
        return {}, errors + [f"{path.name}: recipe must be an object"]

    name = recipe.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{path.name}: recipe.name is required")

    description = recipe.get("description")
    if description is not None and not isinstance(description, str):
        errors.append(f"{path.name}: recipe.description must be a string when provided")

    enabled = recipe.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"{path.name}: recipe.enabled must be a boolean")
    clear_timeout_sec = recipe.get("clear_timeout_sec")
    if clear_timeout_sec is not None:
        try:
            clear_timeout_sec = int(clear_timeout_sec)
        except Exception:  # noqa: BLE001
            errors.append(f"{path.name}: recipe.clear_timeout_sec must be an integer when provided")
        else:
            if clear_timeout_sec < 1:
                errors.append(f"{path.name}: recipe.clear_timeout_sec must be >= 1")

    step_entries = recipe.get("recipe_ingredients", [])
    if not isinstance(step_entries, list) or len(step_entries) == 0:
        errors.append(f"{path.name}: recipe.recipe_ingredients must be a non-empty list")
        return {}, errors

    recipe_ingredients: list[dict[str, Any]] = []
    for idx, entry in enumerate(step_entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"{path.name}: recipe_ingredients[{idx}] must be an object")
            continue
        parsed, step_error = _validate_recipe_step(path.name, idx, entry)
        if step_error:
            errors.append(step_error)
            continue
        recipe_ingredients.append(parsed)

    if errors:
        return {}, errors
    return {
        "name": name,
        "description": description,
        "enabled": enabled,
        "clear_timeout_sec": clear_timeout_sec,
        "recipe_ingredients": recipe_ingredients,
    }, []


def _validate_recipe_step(
    filename: str,
    idx: int,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    engine = entry.get("execution_engine")
    target = entry.get("execution_target")
    destination_target = normalize_destination_target(entry.get("destination_target"))
    task_key_template = entry.get("task_key_template")
    if not isinstance(engine, str) or not engine:
        return {}, f"{filename}: recipe_ingredients[{idx}].execution_engine is required"
    if not isinstance(target, str) or not target:
        return {}, f"{filename}: recipe_ingredients[{idx}].execution_target is required"
    if engine == "bakery":
        target = normalize_destination_type(target)
    if task_key_template is not None and (
        not isinstance(task_key_template, str) or not task_key_template
    ):
        return {}, f"{filename}: recipe_ingredients[{idx}].task_key_template must be a string"

    try:
        step_order = int(entry.get("step_order", 1))
        parallel_group = int(entry.get("parallel_group", 0))
        depth = int(entry.get("depth", 0))
    except Exception:  # noqa: BLE001
        return {}, f"{filename}: recipe_ingredients[{idx}] numeric fields must be integers"

    if step_order < 1:
        return {}, f"{filename}: recipe_ingredients[{idx}].step_order must be >= 1"
    if parallel_group < 0:
        return {}, f"{filename}: recipe_ingredients[{idx}].parallel_group must be >= 0"
    if depth < 0:
        return {}, f"{filename}: recipe_ingredients[{idx}].depth must be >= 0"

    run_phase = entry.get("run_phase", "both")
    if run_phase not in VALID_RUN_PHASES:
        return (
            {},
            f"{filename}: recipe_ingredients[{idx}].run_phase must be one of: "
            f"{', '.join(sorted(VALID_RUN_PHASES))}",
        )

    on_success = entry.get("on_success", "continue")
    if on_success not in VALID_ON_SUCCESS:
        return (
            {},
            f"{filename}: recipe_ingredients[{idx}].on_success must be one of: "
            f"{', '.join(sorted(VALID_ON_SUCCESS))}",
        )

    override = entry.get("execution_parameters_override")
    if override is not None and not isinstance(override, dict):
        return (
            {},
            f"{filename}: recipe_ingredients[{idx}].execution_parameters_override must be "
            "an object when provided",
        )
    payload_override = entry.get("execution_payload_override")
    if payload_override is not None and not isinstance(payload_override, dict):
        return (
            {},
            f"{filename}: recipe_ingredients[{idx}].execution_payload_override must be "
            "an object when provided",
        )
    expected_duration_sec_override = entry.get("expected_duration_sec_override")
    if expected_duration_sec_override is not None:
        try:
            expected_duration_sec_override = int(expected_duration_sec_override)
        except Exception:  # noqa: BLE001
            return (
                {},
                f"{filename}: recipe_ingredients[{idx}].expected_duration_sec_override must be an integer",
            )
        if expected_duration_sec_override < 1:
            return (
                {},
                f"{filename}: recipe_ingredients[{idx}].expected_duration_sec_override must be >= 1",
            )
    timeout_duration_sec_override = entry.get("timeout_duration_sec_override")
    if timeout_duration_sec_override is not None:
        try:
            timeout_duration_sec_override = int(timeout_duration_sec_override)
        except Exception:  # noqa: BLE001
            return (
                {},
                f"{filename}: recipe_ingredients[{idx}].timeout_duration_sec_override must be an integer",
            )
        if timeout_duration_sec_override < 1:
            return (
                {},
                f"{filename}: recipe_ingredients[{idx}].timeout_duration_sec_override must be >= 1",
            )
    run_condition = normalize_run_condition(entry.get("run_condition"))
    if run_condition not in RUN_CONDITIONS:
        return (
            {},
            f"{filename}: recipe_ingredients[{idx}].run_condition must be one of: "
            f"{', '.join(sorted(RUN_CONDITIONS))}",
        )

    return {
        "execution_engine": engine,
        "execution_target": target,
        "destination_target": destination_target,
        "task_key_template": task_key_template,
        "step_order": step_order,
        "on_success": on_success,
        "parallel_group": parallel_group,
        "depth": depth,
        "execution_payload_override": payload_override,
        "run_phase": run_phase,
        "run_condition": run_condition,
        "execution_parameters_override": override,
        "expected_duration_sec_override": expected_duration_sec_override,
        "timeout_duration_sec_override": timeout_duration_sec_override,
    }, None


async def upsert_bootstrap_recipe_catalog(
    db: AsyncSession,
    *,
    recipes_dir: str,
) -> dict[str, Any]:
    """Upsert bootstrap recipe catalog entries into recipes + recipe_ingredients."""
    recipes, load_errors = load_bootstrap_recipe_catalog(recipes_dir)
    if load_errors:
        logger.warning(
            "Bootstrap recipe catalog validation errors",
            extra={"directory": recipes_dir, "errors": load_errors},
        )

    # Resolve all referenced ingredients in one query.
    refs: set[tuple[str, str]] = set()
    for recipe in recipes:
        for step in recipe["recipe_ingredients"]:
            refs.add((step["execution_engine"], step["execution_target"]))

    ingredient_map: dict[tuple[str, str, str, str], Ingredient] = {}
    ingredient_candidates: dict[tuple[str, str], list[Ingredient]] = {}
    if refs:
        ingredient_result = await db.execute(
            select(Ingredient).where(
                tuple_(Ingredient.execution_engine, Ingredient.execution_target).in_(list(refs))
            )
        )
        for row in ingredient_result.scalars().all():
            exact_key = (
                row.execution_engine,
                row.execution_target,
                normalize_destination_target(getattr(row, "destination_target", "")),
                getattr(row, "task_key_template", "") or "",
            )
            ingredient_map[exact_key] = row
            ingredient_candidates.setdefault(
                (row.execution_engine, row.execution_target), []
            ).append(row)

    # Any missing ingredient reference is a hard per-entry validation failure.
    valid_recipes: list[dict[str, Any]] = []
    for recipe in recipes:
        missing_refs: list[str] = []
        for step in recipe["recipe_ingredients"]:
            exact_key = (
                step["execution_engine"],
                step["execution_target"],
                step["destination_target"],
                step["task_key_template"] or "",
            )
            ingredient = None
            if step["task_key_template"] is not None:
                ingredient = ingredient_map.get(exact_key)
            else:
                candidates = ingredient_candidates.get(
                    (step["execution_engine"], step["execution_target"]),
                    [],
                )
                if len(candidates) == 1:
                    ingredient = candidates[0]
                elif len(candidates) > 1:
                    missing_refs.append(
                        f"{step['execution_engine']}:{step['execution_target']} (ambiguous; add task_key_template)"
                    )
                    continue
            if ingredient is None:
                missing_refs.append(f"{step['execution_engine']}:{step['execution_target']}")
                continue
            step["resolved_ingredient_id"] = ingredient.id
        if missing_refs:
            load_errors.append(
                f"recipe '{recipe['name']}': missing ingredient refs: {', '.join(sorted(missing_refs))}"
            )
            continue
        valid_recipes.append(recipe)

    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    skipped = 0
    processed = 0
    conflicts = 0
    obsolete_deleted = 0

    def _step_signature(step: RecipeIngredient | dict[str, Any]) -> tuple[Any, ...]:
        if isinstance(step, RecipeIngredient):
            return (
                step.ingredient_id,
                step.step_order,
                step.on_success,
                step.parallel_group,
                step.depth,
                step.execution_payload_override,
                step.execution_parameters_override,
                step.expected_duration_sec_override,
                step.timeout_duration_sec_override,
                step.run_phase,
                step.run_condition,
            )
        return (
            step["resolved_ingredient_id"],
            step["step_order"],
            step["on_success"],
            step["parallel_group"],
            step["depth"],
            step["execution_payload_override"],
            step["execution_parameters_override"],
            step["expected_duration_sec_override"],
            step["timeout_duration_sec_override"],
            step["run_phase"],
            step["run_condition"],
        )

    for payload in valid_recipes:
        processed += 1
        recipe_name = payload["name"]
        recipe_result = await db.execute(
            select(Recipe)
            .options(selectinload(Recipe.recipe_ingredients))
            .where(Recipe.name == recipe_name)
        )
        db_recipe: Recipe | None = recipe_result.scalars().first()
        if db_recipe is None:
            db_recipe = Recipe(
                name=recipe_name,
                description=payload["description"],
                enabled=payload["enabled"],
                clear_timeout_sec=payload["clear_timeout_sec"],
                deleted=False,
                deleted_at=None,
                updated_at=now,
            )
            db.add(db_recipe)
            await db.flush()
            created += 1
        else:
            if not _is_managed_bootstrap_recipe_description(db_recipe.description):
                conflicts += 1
                load_errors.append(
                    f"recipe '{recipe_name}': existing non-managed recipe conflicts with managed bootstrap sync"
                )
                continue
            changed = False
            if db_recipe.description != payload["description"]:
                db_recipe.description = payload["description"]
                changed = True
            if db_recipe.enabled != payload["enabled"]:
                db_recipe.enabled = payload["enabled"]
                changed = True
            if db_recipe.clear_timeout_sec != payload["clear_timeout_sec"]:
                db_recipe.clear_timeout_sec = payload["clear_timeout_sec"]
                changed = True
            if db_recipe.deleted is True or db_recipe.deleted_at is not None:
                db_recipe.deleted = False
                db_recipe.deleted_at = None
                changed = True
            existing_steps = [
                _step_signature(step)
                for step in sorted(db_recipe.recipe_ingredients, key=lambda s: s.step_order)
            ]
            desired_steps = [
                _step_signature(step)
                for step in sorted(payload["recipe_ingredients"], key=lambda s: s["step_order"])
            ]
            steps_changed = existing_steps != desired_steps
            if changed or steps_changed:
                db_recipe.updated_at = now
                updated += 1
            else:
                skipped += 1
                continue

        await delete_recipe_ingredients_safely(db, recipe_id=db_recipe.id)
        for step in sorted(payload["recipe_ingredients"], key=lambda s: s["step_order"]):
            db.add(
                RecipeIngredient(
                    recipe_id=db_recipe.id,
                    ingredient_id=step["resolved_ingredient_id"],
                    step_order=step["step_order"],
                    on_success=step["on_success"],
                    parallel_group=step["parallel_group"],
                    depth=step["depth"],
                    execution_payload_override=step["execution_payload_override"],
                    execution_parameters_override=step["execution_parameters_override"],
                    expected_duration_sec_override=step["expected_duration_sec_override"],
                    timeout_duration_sec_override=step["timeout_duration_sec_override"],
                    run_phase=step["run_phase"],
                    run_condition=step["run_condition"],
                )
            )

    if not load_errors:
        valid_recipe_names = {payload["name"] for payload in valid_recipes}
        obsolete_query = select(Recipe).where(
            Recipe.deleted.is_(False),
            Recipe.enabled.is_(True),
            ~Recipe.name.in_(valid_recipe_names),
        )
        obsolete_result = await db.execute(obsolete_query)
        for obsolete_recipe in cast(list[Recipe], obsolete_result.scalars().all()):
            if not _is_managed_bootstrap_recipe_description(obsolete_recipe.description):
                continue
            await delete_recipe_ingredients_safely(db, recipe_id=obsolete_recipe.id)
            obsolete_recipe.enabled = False
            obsolete_recipe.deleted = True
            obsolete_recipe.deleted_at = now
            obsolete_recipe.updated_at = now
            obsolete_deleted += 1

    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "unchanged": skipped,
        "skipped": skipped,
        "processed": processed,
        "conflicts": conflicts,
        "obsolete_deleted": obsolete_deleted,
        "errors": len(load_errors),
        "error_messages": load_errors,
        "source": recipes_dir,
    }

"""Bootstrap recipe catalog loader/upsert helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient

logger = get_logger(__name__)

CATALOG_API_VERSION = "poundcake/v1"
CATALOG_KIND = "RecipeCatalogEntry"
VALID_RUN_PHASES = {"firing", "resolving", "both"}
VALID_ON_SUCCESS = {"continue", "stop"}


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
        "recipe_ingredients": recipe_ingredients,
    }, []


def _validate_recipe_step(
    filename: str,
    idx: int,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    engine = entry.get("execution_engine")
    target = entry.get("execution_target")
    if not isinstance(engine, str) or not engine:
        return {}, f"{filename}: recipe_ingredients[{idx}].execution_engine is required"
    if not isinstance(target, str) or not target:
        return {}, f"{filename}: recipe_ingredients[{idx}].execution_target is required"

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

    return {
        "execution_engine": engine,
        "execution_target": target,
        "step_order": step_order,
        "on_success": on_success,
        "parallel_group": parallel_group,
        "depth": depth,
        "run_phase": run_phase,
        "execution_parameters_override": override,
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

    ingredient_map: dict[tuple[str, str], Ingredient] = {}
    if refs:
        result = await db.execute(
            select(Ingredient).where(
                tuple_(Ingredient.execution_engine, Ingredient.execution_target).in_(list(refs))
            )
        )
        ingredient_map = {
            (row.execution_engine, row.execution_target): row for row in result.scalars().all()
        }

    # Any missing ingredient reference is a hard per-entry validation failure.
    valid_recipes: list[dict[str, Any]] = []
    for recipe in recipes:
        missing_refs: list[str] = []
        for step in recipe["recipe_ingredients"]:
            key = (step["execution_engine"], step["execution_target"])
            if key not in ingredient_map:
                missing_refs.append(f"{key[0]}:{key[1]}")
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

    for payload in valid_recipes:
        processed += 1
        recipe_name = payload["name"]
        result = await db.execute(select(Recipe).where(Recipe.name == recipe_name))
        recipe = result.scalars().first()
        if recipe is None:
            recipe = Recipe(
                name=recipe_name,
                description=payload["description"],
                enabled=payload["enabled"],
                deleted=False,
                deleted_at=None,
                updated_at=now,
            )
            db.add(recipe)
            await db.flush()
            created += 1
        else:
            changed = False
            if recipe.description != payload["description"]:
                recipe.description = payload["description"]
                changed = True
            if recipe.enabled != payload["enabled"]:
                recipe.enabled = payload["enabled"]
                changed = True
            if recipe.deleted is True or recipe.deleted_at is not None:
                recipe.deleted = False
                recipe.deleted_at = None
                changed = True
            if changed:
                recipe.updated_at = now
                updated += 1
            else:
                skipped += 1

        await db.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id))
        for step in sorted(payload["recipe_ingredients"], key=lambda s: s["step_order"]):
            key = (step["execution_engine"], step["execution_target"])
            ingredient = ingredient_map[key]
            db.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    step_order=step["step_order"],
                    on_success=step["on_success"],
                    parallel_group=step["parallel_group"],
                    depth=step["depth"],
                    execution_parameters_override=step["execution_parameters_override"],
                    run_phase=step["run_phase"],
                )
            )

    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "processed": processed,
        "errors": len(load_errors),
        "error_messages": load_errors,
        "source": recipes_dir,
    }

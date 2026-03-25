#  ____                        _  ____      _
# |  _ \\ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \\| | | | '_ \\ / _` | |   / _` | |/ / _ \\
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \\___/ \\__,_|_| |_|\\__,_|\\____\\__,_|_|\\_\\___|
#
"""Dishwasher service: sync StackStorm actions into Ingredients/Recipes."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import SessionLocal
from api.core.config import get_settings
from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.services.bootstrap_ingredient_catalog import upsert_bootstrap_ingredient_catalogs
from api.services.bootstrap_remote_recipe_sync import (
    BootstrapRemoteRecipeSyncError,
    refresh_bootstrap_recipe_catalog_from_remote,
)
from api.services.bootstrap_recipe_catalog import upsert_bootstrap_recipe_catalog
from api.services.fallback_recipe import ensure_fallback_recipe
from api.services.recipe_ingredient_cleanup import delete_recipe_ingredients_safely
from api.services.stackstorm_service import get_action_manager

logger = get_logger(__name__)

DEFAULT_DURATION = int(os.getenv("DISHWASHER_DEFAULT_DURATION", "60"))
DEFAULT_TIMEOUT = int(os.getenv("DISHWASHER_DEFAULT_TIMEOUT", "300"))
PRUNE_MISSING = os.getenv("DISHWASHER_PRUNE_MISSING", "false").lower() == "true"
STRICT_RECIPE_SYNC = os.getenv("DISHWASHER_STRICT_RECIPE_SYNC", "false").lower() == "true"
BOOTSTRAP_DONE_FILE = "/tmp/poundcake_bootstrap.done"


def _empty_sync_stats(**extra: Any) -> dict[str, Any]:
    payload = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "processed": 0,
        "conflicts": 0,
        "errors": 0,
        "error_messages": [],
        "source": "",
    }
    payload.update(extra)
    return payload


async def sync_stackstorm(mark_bootstrap: bool = False) -> dict[str, Any]:
    """Sync StackStorm actions/workflows into Ingredients/Recipes."""
    manager = get_action_manager()
    actions = await manager.list_non_orquesta_actions(limit=1000)
    workflows = await manager.list_orquesta_actions(limit=1000)
    settings = get_settings()
    ingredients_dir = settings.bootstrap_ingredients_dir
    if not Path(ingredients_dir).exists() and settings.bootstrap_ingredients_file:
        legacy_file = Path(settings.bootstrap_ingredients_file)
        if legacy_file.exists():
            ingredients_dir = str(legacy_file.parent)

    async with SessionLocal() as db:
        ingredient_stats = await upsert_ingredients(db, actions)
        recipe_stats = await upsert_recipes(db, workflows)
        bootstrap_catalog_stats = {
            "ingredients": _empty_sync_stats(files_scanned=0),
            "recipes": _empty_sync_stats(files_scanned=0, rules_discovered=0, generated=0),
            "remote_recipes": {
                "enabled": bool(settings.bootstrap_remote_sync_enabled),
                "refreshed": False,
                "files_scanned": 0,
                "rules_discovered": 0,
                "generated": 0,
                "errors": 0,
                "error_messages": [],
                "source": settings.bootstrap_recipes_dir,
                "repo_url": settings.bootstrap_rules_repo_url,
                "branch": settings.bootstrap_rules_branch,
                "path": settings.bootstrap_rules_path,
            },
        }
        bootstrap_catalog_stats["ingredients"] = await upsert_bootstrap_ingredient_catalogs(
            db, ingredients_dir=ingredients_dir
        )
        if mark_bootstrap and bootstrap_catalog_stats["ingredients"]["errors"]:
            raise RuntimeError(
                "Bootstrap ingredient catalog sync failed: "
                + "; ".join(bootstrap_catalog_stats["ingredients"]["error_messages"])
            )

        if settings.bootstrap_remote_sync_enabled:
            try:
                bootstrap_catalog_stats["remote_recipes"] = (
                    refresh_bootstrap_recipe_catalog_from_remote(
                        repo_url=settings.bootstrap_rules_repo_url,
                        branch=settings.bootstrap_rules_branch,
                        rules_path=settings.bootstrap_rules_path,
                        destination_dir=settings.bootstrap_recipes_dir,
                    )
                )
            except BootstrapRemoteRecipeSyncError as exc:
                bootstrap_catalog_stats["remote_recipes"]["errors"] = 1
                bootstrap_catalog_stats["remote_recipes"]["error_messages"] = [str(exc)]
                logger.warning(
                    "Remote bootstrap recipe refresh failed",
                    extra={
                        "mark_bootstrap": mark_bootstrap,
                        "error": str(exc),
                        "repo_url": settings.bootstrap_rules_repo_url,
                        "branch": settings.bootstrap_rules_branch,
                        "rules_path": settings.bootstrap_rules_path,
                    },
                )
                if mark_bootstrap:
                    raise

        if mark_bootstrap or settings.bootstrap_remote_sync_enabled:
            bootstrap_catalog_stats["recipes"] = await upsert_bootstrap_recipe_catalog(
                db, recipes_dir=settings.bootstrap_recipes_dir
            )
            if mark_bootstrap and (
                bootstrap_catalog_stats["recipes"]["errors"]
                or bootstrap_catalog_stats["recipes"]["conflicts"]
            ):
                recipe_errors = list(bootstrap_catalog_stats["recipes"]["error_messages"])
                if bootstrap_catalog_stats["recipes"]["conflicts"]:
                    recipe_errors.append(
                        f"{bootstrap_catalog_stats['recipes']['conflicts']} recipe conflict(s)"
                    )
                raise RuntimeError(
                    "Bootstrap recipe catalog sync failed: " + "; ".join(recipe_errors)
                )
            await ensure_fallback_recipe(db, req_id="SYSTEM-DISHWASHER")
            await db.commit()

    stats: dict[str, Any] = {}
    stats["ingredients"] = ingredient_stats
    stats["recipes"] = recipe_stats
    stats["bootstrap_catalog"] = bootstrap_catalog_stats

    if mark_bootstrap:
        try:
            with open(BOOTSTRAP_DONE_FILE, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
            stats["bootstrap_marked"] = True
        except Exception as e:
            logger.warning(
                "Failed to mark bootstrap completion",
                extra={"error": str(e), "file": BOOTSTRAP_DONE_FILE},
            )
            stats["bootstrap_marked"] = False

    return stats


async def upsert_ingredients(db: AsyncSession, actions: list[dict]) -> dict[str, int]:
    created = 0
    updated = 0
    pruned = 0
    now = datetime.now(timezone.utc)

    # Only sync ingredients with execution_engine="stackstorm"
    result = await db.execute(select(Ingredient).where(Ingredient.execution_engine == "stackstorm"))
    existing_rows = result.scalars().all()
    existing_by_identity = {
        (ing.execution_target, ing.task_key_template or ""): ing for ing in existing_rows
    }
    existing_by_execution_id = {
        str(ing.execution_id): ing for ing in existing_rows if getattr(ing, "execution_id", None)
    }
    existing_by_target: dict[str, list[Ingredient]] = {}
    for ing in existing_rows:
        existing_by_target.setdefault(ing.execution_target, []).append(ing)
    action_refs = set()

    for action in actions:
        action_ref = action.get("ref") or action.get("name")
        if not action_ref:
            continue
        action_refs.add(action_ref)

        task_name = action.get("name") or action_ref
        ing = existing_by_identity.get((action_ref, task_name))
        if ing is None:
            action_id = action.get("id")
            if action_id:
                ing = existing_by_execution_id.get(str(action_id))
        if ing is None:
            target_matches = existing_by_target.get(action_ref, [])
            if len(target_matches) == 1:
                candidate = target_matches[0]
                candidate_task_name = candidate.task_key_template or ""
                if candidate_task_name in {"", task_name}:
                    ing = candidate

        payload = action
        parameters = action.get("parameters") or {}

        if ing is None:
            ing = Ingredient(
                execution_target=action_ref,
                task_key_template=task_name,
                execution_id=action.get("id"),
                execution_payload=payload,
                execution_parameters=parameters,
                execution_engine="stackstorm",
                execution_purpose="remediation",
                is_blocking=True,
                expected_duration_sec=DEFAULT_DURATION,
                timeout_duration_sec=DEFAULT_TIMEOUT,
                retry_count=0,
                retry_delay=5,
                on_failure="stop",
                deleted=False,
                deleted_at=None,
                updated_at=now,
            )
            db.add(ing)
            existing_by_identity[(action_ref, task_name)] = ing
            if getattr(ing, "execution_id", None):
                existing_by_execution_id[str(ing.execution_id)] = ing
            existing_by_target.setdefault(action_ref, []).append(ing)
            created += 1
        else:
            # Only update if something actually changed
            changed = False
            new_task_name = task_name or ing.task_key_template
            new_action_id = action.get("id")

            if (
                ing.task_key_template != new_task_name
                or ing.execution_id != new_action_id
                or ing.execution_payload != payload
                or ing.execution_parameters != parameters
                or ing.execution_engine != "stackstorm"
                or ing.deleted is True
                or ing.deleted_at is not None
            ):
                ing.task_key_template = new_task_name
                ing.execution_id = new_action_id
                ing.execution_payload = payload
                ing.execution_parameters = parameters
                ing.execution_engine = "stackstorm"
                ing.execution_purpose = "remediation"
                ing.deleted = False
                ing.deleted_at = None
                ing.updated_at = now
                changed = True

            if changed:
                existing_by_identity[(action_ref, new_task_name)] = ing
                if new_action_id:
                    existing_by_execution_id[str(new_action_id)] = ing
                updated += 1

    # Only prune StackStorm ingredients (existing dict already filtered by execution_engine)
    if PRUNE_MISSING:
        for ing in existing_rows:
            ref = ing.execution_target
            if ref not in action_refs:
                ing.deleted = True
                ing.deleted_at = now
                ing.updated_at = now
                pruned += 1

    await db.commit()
    return {"created": created, "updated": updated, "pruned": pruned}


async def upsert_recipes(db: AsyncSession, actions: list[dict]) -> dict[str, int]:
    created = 0
    updated = 0
    now = datetime.now(timezone.utc)

    result = await db.execute(select(Recipe))
    existing = {rec.name: rec for rec in result.scalars().all()}

    for action in actions:
        workflow_id = action.get("ref")
        if not workflow_id:
            continue

        name = action.get("name") or workflow_id
        description = action.get("description")
        workflow_payload = action.get("data")
        if isinstance(workflow_payload, str):
            try:
                workflow_payload = yaml.safe_load(workflow_payload) or {}
            except Exception:
                workflow_payload = None
        rec = existing.get(name)
        if rec is None:
            rec = Recipe(
                name=name,
                description=description,
                enabled=True,
                deleted=False,
                deleted_at=None,
                updated_at=now,
            )
            db.add(rec)
            await db.flush()
            created += 1
        else:
            rec.name = name
            rec.description = description
            rec.deleted = False
            rec.deleted_at = None
            rec.updated_at = now
            updated += 1

        if workflow_payload:
            ok = await sync_recipe_ingredients_from_yaml(
                db, rec, workflow_payload, strict=STRICT_RECIPE_SYNC
            )
            if not ok and STRICT_RECIPE_SYNC:
                logger.warning(
                    "Recipe sync failed due to missing ingredients",
                    extra={"workflow_id": workflow_id, "recipe_id": rec.id},
                )

    await db.commit()
    return {"created": created, "updated": updated}


async def sync_recipe_ingredients_from_yaml(
    db: AsyncSession,
    recipe: Recipe,
    yaml_payload: dict[str, Any] | str,
    strict: bool = False,
) -> bool:
    """
    Parse Orquesta YAML tasks and build recipe_ingredients.
    Returns False if missing ingredients and strict=True.
    """
    try:
        workflow = json.loads(json.dumps(yaml_payload))
        if isinstance(yaml_payload, str):
            workflow = yaml.safe_load(yaml_payload) or {}
    except Exception as e:
        logger.warning(
            "Failed to parse Orquesta YAML",
            extra={"recipe_id": recipe.id, "error": str(e)},
        )
        return not strict

    tasks = workflow.get("tasks", {}) if isinstance(workflow, dict) else {}
    if not isinstance(tasks, dict) or not tasks:
        return not strict

    edges: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}
    task_actions: dict[str, str] = {}

    for task_name, task_def in tasks.items():
        action_ref = (task_def or {}).get("action")
        if not action_ref:
            continue
        task_actions[task_name] = action_ref
        indegree.setdefault(task_name, 0)
        edges.setdefault(task_name, [])
        for nxt in (task_def or {}).get("next", []) or []:
            nxt_name = nxt.get("do")
            if nxt_name:
                edges.setdefault(task_name, []).append(nxt_name)
                indegree[nxt_name] = indegree.get(nxt_name, 0) + 1

    queue = [t for t, deg in indegree.items() if deg == 0]
    ordered_tasks = []
    depth_map = {t: 0 for t in queue}
    while queue:
        t = queue.pop(0)
        ordered_tasks.append(t)
        for nxt in edges.get(t, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                depth_map[nxt] = max(depth_map.get(nxt, 0), depth_map.get(t, 0) + 1)
                queue.append(nxt)

    if not ordered_tasks:
        ordered_tasks = list(task_actions.keys())
        for t in ordered_tasks:
            depth_map.setdefault(t, 0)

    result = await db.execute(select(Ingredient))
    existing_ingredients = {ing.execution_target: ing for ing in result.scalars().all()}
    missing = []
    for task_name in ordered_tasks:
        action_ref = task_actions.get(task_name)
        if not action_ref:
            continue
        if action_ref not in existing_ingredients:
            if strict:
                missing.append(action_ref)
                continue
            stub = Ingredient(
                execution_target=action_ref,
                task_key_template=action_ref,
                execution_id=None,
                execution_payload=None,
                execution_parameters={},
                execution_engine="native",
                execution_purpose="utility",
                is_blocking=True,
                expected_duration_sec=DEFAULT_DURATION,
                timeout_duration_sec=DEFAULT_TIMEOUT,
                retry_count=0,
                retry_delay=5,
                on_failure="stop",
                deleted=False,
                deleted_at=None,
            )
            db.add(stub)
            await db.flush()
            existing_ingredients[action_ref] = stub
            logger.warning(
                "Created stub ingredient for missing action",
                extra={"recipe_id": recipe.id, "action_ref": action_ref},
            )

    if missing and strict:
        logger.warning(
            "Missing ingredients for recipe sync",
            extra={"recipe_id": recipe.id, "missing": missing},
        )
        return False

    await delete_recipe_ingredients_safely(db, recipe_id=recipe.id)

    step_order = 1
    for task_name in ordered_tasks:
        action_ref = task_actions.get(task_name)
        if not action_ref:
            continue
        ing = existing_ingredients.get(action_ref)
        if not ing:
            continue
        depth = depth_map.get(task_name, 0)
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ing.id,
                step_order=step_order,
                on_success="continue",
                parallel_group=depth,
                depth=depth,
                execution_parameters_override=(tasks.get(task_name, {}) or {}).get("input"),
                run_phase="firing",
            )
        )
        step_order += 1

    return True

"""Bootstrap ingredient catalog loader/upsert helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.models.models import Ingredient
from api.services.communications import (
    DESTINATION_TYPES,
    normalize_communication_operation,
    normalize_destination_target,
    normalize_destination_type,
)

logger = get_logger(__name__)

CATALOG_API_VERSION = "poundcake/v1"
CATALOG_KIND = "IngredientCatalog"
CANONICAL_BAKERY_TARGETS = DESTINATION_TYPES
LEGACY_BAKERY_TARGETS = {"tickets.create", "tickets.update", "tickets.comment", "tickets.close"}


def load_bootstrap_ingredient_catalog_file(
    file_path: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load and validate a single bootstrap ingredient catalog YAML file."""
    errors: list[str] = []
    path = Path(file_path)
    if not path.exists():
        return [], [f"catalog file not found: {file_path}"]

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return [], [f"failed to parse catalog yaml: {exc}"]

    if not isinstance(raw, dict):
        return [], ["catalog root must be an object"]

    if raw.get("apiVersion") != CATALOG_API_VERSION:
        errors.append(
            f"catalog apiVersion must be '{CATALOG_API_VERSION}', got '{raw.get('apiVersion')}'"
        )
    if raw.get("kind") != CATALOG_KIND:
        errors.append(f"catalog kind must be '{CATALOG_KIND}', got '{raw.get('kind')}'")

    items = raw.get("ingredients", [])
    if not isinstance(items, list):
        return [], errors + ["catalog ingredients must be a list"]

    parsed: list[dict[str, Any]] = []
    for idx, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            errors.append(f"ingredients[{idx}] must be an object")
            continue
        payload, validation_error = _validate_catalog_entry(entry, idx)
        if validation_error:
            errors.append(validation_error)
            continue
        parsed.append(payload)

    return parsed, errors


def load_bootstrap_ingredient_catalogs(
    ingredients_dir: str,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Load and validate all bootstrap ingredient catalog files from a directory tree."""
    base = Path(ingredients_dir)
    if not base.exists():
        return [], [f"catalog directory not found: {ingredients_dir}"], 0
    if not base.is_dir():
        return [], [f"catalog path is not a directory: {ingredients_dir}"], 0

    payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    files_scanned = 0
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        files_scanned += 1
        items, file_errors = load_bootstrap_ingredient_catalog_file(str(path))
        payloads.extend(items)
        errors.extend(f"{path.relative_to(base)}: {message}" for message in file_errors)
    return payloads, errors, files_scanned


def _validate_catalog_entry(entry: dict[str, Any], idx: int) -> tuple[dict[str, Any], str | None]:
    target = normalize_destination_type(entry.get("execution_target"))
    if not target:
        return {}, f"ingredients[{idx}].execution_target is required"
    if target not in CANONICAL_BAKERY_TARGETS:
        allowed = ", ".join(sorted(CANONICAL_BAKERY_TARGETS))
        return {}, f"ingredients[{idx}].execution_target must be one of: {allowed}"
    destination_target = normalize_destination_target(entry.get("destination_target"))

    engine = entry.get("execution_engine")
    if engine != "bakery":
        return {}, f"ingredients[{idx}].execution_engine must be 'bakery'"

    purpose = entry.get("execution_purpose")
    if purpose != "comms":
        return {}, f"ingredients[{idx}].execution_purpose must be 'comms'"

    task_key_template = entry.get("task_key_template")
    if not isinstance(task_key_template, str) or not task_key_template:
        return {}, f"ingredients[{idx}].task_key_template is required"

    execution_payload = entry.get("execution_payload")
    if execution_payload is not None and not isinstance(execution_payload, dict):
        return {}, f"ingredients[{idx}].execution_payload must be an object when provided"
    template = (execution_payload or {}).get("template")
    if not isinstance(template, dict):
        return {}, f"ingredients[{idx}].execution_payload.template must be an object"

    execution_parameters = entry.get("execution_parameters")
    if execution_parameters is not None and not isinstance(execution_parameters, dict):
        return {}, f"ingredients[{idx}].execution_parameters must be an object when provided"
    operation = normalize_communication_operation((execution_parameters or {}).get("operation"))
    if operation not in {"open", "notify", "update", "close"}:
        return (
            {},
            f"ingredients[{idx}].execution_parameters.operation must be one of: "
            "open, notify, update, close, "
            "ticket_create, ticket_update, ticket_comment, ticket_close",
        )

    on_failure = entry.get("on_failure", "stop")
    if on_failure not in {"stop", "continue"}:
        return {}, f"ingredients[{idx}].on_failure must be one of: stop, continue"

    payload = {
        "execution_target": target,
        "destination_target": destination_target,
        "task_key_template": task_key_template,
        "execution_engine": "bakery",
        "execution_purpose": "comms",
        "execution_id": entry.get("execution_id"),
        "execution_payload": execution_payload,
        "execution_parameters": execution_parameters,
        "is_default": bool(entry.get("is_default", False)),
        "is_active": bool(entry.get("is_active", True)),
        "is_blocking": bool(entry.get("is_blocking", True)),
        "expected_duration_sec": int(entry.get("expected_duration_sec", 30)),
        "timeout_duration_sec": int(entry.get("timeout_duration_sec", 120)),
        "retry_count": int(entry.get("retry_count", 0)),
        "retry_delay": int(entry.get("retry_delay", 5)),
        "on_failure": on_failure,
    }
    if payload["expected_duration_sec"] < 1:
        return {}, f"ingredients[{idx}].expected_duration_sec must be >= 1"
    if payload["timeout_duration_sec"] < 1:
        return {}, f"ingredients[{idx}].timeout_duration_sec must be >= 1"
    if payload["retry_count"] < 0:
        return {}, f"ingredients[{idx}].retry_count must be >= 0"
    if payload["retry_delay"] < 0:
        return {}, f"ingredients[{idx}].retry_delay must be >= 0"

    return payload, None


async def upsert_bootstrap_ingredient_catalogs(
    db: AsyncSession,
    *,
    ingredients_dir: str,
) -> dict[str, Any]:
    """Upsert bootstrap-managed ingredients from catalog YAML files."""
    payloads, load_errors, files_scanned = load_bootstrap_ingredient_catalogs(ingredients_dir)
    if load_errors:
        logger.warning(
            "Bootstrap ingredient catalog validation errors",
            extra={"directory": ingredients_dir, "errors": load_errors},
        )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Ingredient).where(
            Ingredient.execution_engine == "bakery",
            Ingredient.execution_target.in_(
                tuple(sorted(CANONICAL_BAKERY_TARGETS | LEGACY_BAKERY_TARGETS))
            ),
        )
    )
    existing_by_target = {
        (
            row.execution_target,
            normalize_destination_target(getattr(row, "destination_target", "")),
            getattr(row, "task_key_template", "") or "",
        ): row
        for row in result.scalars().all()
    }

    created = 0
    updated = 0
    skipped = 0
    for payload in payloads:
        target_key = (
            payload["execution_target"],
            payload["destination_target"],
            payload["task_key_template"],
        )
        ingredient = existing_by_target.get(target_key)

        if ingredient is None:
            ingredient = Ingredient(**payload, deleted=False, deleted_at=None, updated_at=now)
            db.add(ingredient)
            created += 1
            continue

        changed = False
        for key, value in payload.items():
            if getattr(ingredient, key) != value:
                setattr(ingredient, key, value)
                changed = True
        if ingredient.deleted is True or ingredient.deleted_at is not None:
            ingredient.deleted = False
            ingredient.deleted_at = None
            changed = True
        if changed:
            ingredient.updated_at = now
            updated += 1
        else:
            skipped += 1

    # Hard-cut cleanup: soft-delete legacy bootstrap-managed tickets.* targets.
    for target in sorted(LEGACY_BAKERY_TARGETS):
        for key, legacy in existing_by_target.items():
            if key[0] != target:
                continue
            if legacy.deleted is False or legacy.deleted_at is None:
                legacy.deleted = True
                legacy.deleted_at = now
                legacy.updated_at = now
                updated += 1

    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "unchanged": skipped,
        "skipped": skipped,
        "errors": len(load_errors),
        "error_messages": load_errors,
        "source": ingredients_dir,
        "files_scanned": files_scanned,
    }


def load_bootstrap_ingredient_catalog(
    file_path: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Backward-compatible single-file loader alias."""
    return load_bootstrap_ingredient_catalog_file(file_path)


async def upsert_bootstrap_bakery_ingredients(
    db: AsyncSession,
    *,
    file_path: str,
) -> dict[str, Any]:
    """Backward-compatible single-file upsert wrapper."""
    path = Path(file_path)
    ingredients_dir = str(path.parent) if path.name else file_path
    return await upsert_bootstrap_ingredient_catalogs(db, ingredients_dir=ingredients_dir)

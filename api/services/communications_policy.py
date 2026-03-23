"""Managed global and workflow-local communications policy helpers."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.config import get_settings
from api.models.models import DishIngredient, Ingredient, Recipe, RecipeIngredient
from api.services.bakery_payloads import resolve_bakery_payload
from api.services.communications import (
    normalize_destination_target,
    normalize_destination_type,
    normalize_route_provider_config,
)

MANAGED_TASK_PREFIX = "pcmcomms."
MANAGED_RECIPE_NAME_GLOBAL = "pcm-policy-global"
MANAGED_DESCRIPTION_FALLBACK = "[managed-comms:fallback]"
MANAGED_DESCRIPTION_GLOBAL = "[managed-comms:global]"
POLICY_METADATA_KEY = "poundcake_policy"

MATCHED_ROUTE_EVENTS = (
    ("escalation_open", "open", "escalation", "always", 1000),
    ("resolved_success_open", "open", "resolving", "resolved_after_success", 2000),
    ("resolved_success_close", "close", "resolving", "resolved_after_success", 2001),
    ("resolved_failure_notify", "notify", "resolving", "resolved_after_failure", 2100),
    ("resolved_timeout_notify", "notify", "resolving", "resolved_after_timeout", 2200),
)

FALLBACK_ROUTE_EVENTS = (
    ("fallback_open", "open", "firing", "always", 1000),
    ("fallback_notify", "notify", "resolving", "resolved_after_no_remediation", 2000),
)


@dataclass(slots=True)
class CommunicationRoute:
    id: str
    label: str
    execution_target: str
    destination_target: str
    provider_config: dict[str, Any]
    enabled: bool
    position: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "route"


def _coerce_route_id(
    value: Any, *, execution_target: str, destination_target: str, position: int
) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    base = "-".join(
        part
        for part in (
            _slug(execution_target),
            _slug(destination_target or "default"),
            str(position),
        )
        if part
    )
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _metadata_from_payload(execution_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = resolve_bakery_payload(execution_payload)
    context = payload.get("context")
    if not isinstance(context, dict):
        return {}
    metadata = context.get(POLICY_METADATA_KEY)
    return metadata if isinstance(metadata, dict) else {}


def is_managed_communications_ingredient(ingredient: Ingredient | None) -> bool:
    if ingredient is None:
        return False
    return str(getattr(ingredient, "task_key_template", "") or "").startswith(MANAGED_TASK_PREFIX)


def is_communication_ingredient(ingredient: Ingredient | None) -> bool:
    if ingredient is None:
        return False
    if str(getattr(ingredient, "execution_engine", "") or "").strip().lower() != "bakery":
        return False
    return str(getattr(ingredient, "execution_purpose", "") or "").strip().lower() == "comms"


def is_communication_step(recipe_ingredient: RecipeIngredient | Any) -> bool:
    return is_communication_ingredient(getattr(recipe_ingredient, "ingredient", None))


def is_hidden_workflow_recipe(recipe: Recipe | None) -> bool:
    if recipe is None:
        return False
    if (recipe.name or "") == MANAGED_RECIPE_NAME_GLOBAL:
        return True
    description = str(recipe.description or "")
    settings = get_settings()
    catch_all_name = str(settings.catch_all_recipe_name or "").strip()
    if catch_all_name and recipe.name == catch_all_name:
        return True
    return description.startswith(MANAGED_DESCRIPTION_FALLBACK)


def is_route_available_for_update(
    *,
    order: Any,
    execution_target: str,
    destination_target: str,
) -> bool:
    normalized_target = normalize_destination_type(execution_target)
    normalized_destination = normalize_destination_target(destination_target)
    for communication in getattr(order, "communications", []) or []:
        if (
            normalize_destination_type(getattr(communication, "execution_target", ""))
            != normalized_target
        ):
            continue
        if (
            normalize_destination_target(getattr(communication, "destination_target", ""))
            != normalized_destination
        ):
            continue
        if str(getattr(communication, "bakery_ticket_id", "") or "").strip():
            return True
    return False


def _route_from_metadata(metadata: dict[str, Any]) -> CommunicationRoute | None:
    route_id = str(metadata.get("route_id") or "").strip()
    execution_target = normalize_destination_type(metadata.get("execution_target"))
    if not route_id or not execution_target:
        return None
    return CommunicationRoute(
        id=route_id,
        label=str(metadata.get("label") or "").strip()
        or titleize_route(execution_target, metadata.get("destination_target")),
        execution_target=execution_target,
        destination_target=normalize_destination_target(metadata.get("destination_target")),
        provider_config=normalize_route_provider_config(
            execution_target,
            metadata.get("provider_config"),
            require_required=False,
        ),
        enabled=bool(metadata.get("enabled", True)),
        position=int(metadata.get("position") or 0),
    )


def titleize_route(execution_target: str, destination_target: Any) -> str:
    target = normalize_destination_type(execution_target).replace("_", " ").title()
    destination = normalize_destination_target(destination_target)
    return f"{target} - {destination}" if destination else target


def normalize_routes(
    routes: list[dict[str, Any]] | list[CommunicationRoute],
) -> list[CommunicationRoute]:
    normalized: list[CommunicationRoute] = []
    for index, item in enumerate(routes, start=1):
        if isinstance(item, dict):
            raw = item
        elif is_dataclass(item):
            raw = asdict(item)
        else:
            raw = getattr(item, "__dict__", {})
        execution_target = normalize_destination_type(raw.get("execution_target"))
        if not execution_target:
            continue
        destination_target = normalize_destination_target(raw.get("destination_target"))
        position = int(raw.get("position") or index)
        route = CommunicationRoute(
            id=_coerce_route_id(
                raw.get("id"),
                execution_target=execution_target,
                destination_target=destination_target,
                position=position,
            ),
            label=str(raw.get("label") or "").strip()
            or titleize_route(execution_target, destination_target),
            execution_target=execution_target,
            destination_target=destination_target,
            provider_config=normalize_route_provider_config(
                execution_target,
                raw.get("provider_config"),
            ),
            enabled=bool(raw.get("enabled", True)),
            position=position,
        )
        normalized.append(route)
    normalized.sort(key=lambda item: (item.position, item.label.lower(), item.execution_target))
    for index, route in enumerate(normalized, start=1):
        route.position = index
    return normalized


def _managed_task_key(
    *,
    scope: str,
    owner_key: str,
    route_id: str,
    event_name: str,
) -> str:
    return f"{MANAGED_TASK_PREFIX}{scope}.{owner_key}.{route_id}.{event_name}"


def _managed_payload(
    *,
    route: CommunicationRoute,
    scope: str,
    owner_key: str,
    event_name: str,
) -> dict[str, Any]:
    semantic_text = {
        "escalation_open": {
            "headline": "Alert requires attention",
            "summary": "PoundCake escalated this alert because automated remediation failed or timed out.",
            "detail": "Automated remediation did not complete successfully.",
            "resolution": "",
        },
        "resolved_success_open": {
            "headline": "Alert cleared after successful auto-remediation",
            "summary": "PoundCake remediated this alert successfully and is closing the communication now that the alert has cleared.",
            "detail": "Alert cleared after successful auto-remediation.",
            "resolution": "Closing communication after successful auto-remediation.",
        },
        "resolved_success_close": {
            "headline": "Alert resolved",
            "summary": "PoundCake is closing this communication because the alert cleared after successful auto-remediation.",
            "detail": "Alert resolved after successful auto-remediation.",
            "resolution": "Closing communication.",
        },
        "resolved_failure_notify": {
            "headline": "Alert cleared after escalation",
            "summary": "The alert cleared after an escalated communication was already opened.",
            "detail": "Leaving the communication open for the responder.",
            "resolution": "",
        },
        "resolved_timeout_notify": {
            "headline": "Alert cleared after timeout escalation",
            "summary": "The alert cleared after automation timed out and a communication was already opened.",
            "detail": "Leaving the communication open for the responder.",
            "resolution": "",
        },
        "fallback_open": {
            "headline": "Alert requires attention",
            "summary": "PoundCake did not find a matching workflow for this alert and opened a communication for human response.",
            "detail": "No matching workflow is configured for this alert.",
            "resolution": "",
        },
        "fallback_notify": {
            "headline": "Alert cleared",
            "summary": "The unmatched alert has cleared after a fallback communication was already opened.",
            "detail": "Leaving the existing communication open for the responder.",
            "resolution": "",
        },
    }[event_name]
    metadata = {
        "managed": True,
        "scope": scope,
        "owner_key": owner_key,
        "route_id": route.id,
        "label": route.label,
        "execution_target": route.execution_target,
        "destination_target": route.destination_target,
        "provider_config": route.provider_config,
        "enabled": route.enabled,
        "position": route.position,
        "event": event_name,
    }
    return {
        "template": {
            "title": semantic_text["headline"],
            "description": semantic_text["summary"],
            "message": semantic_text["detail"],
            "source": "poundcake",
            "context": {
                "source": "poundcake",
                "route_label": route.label,
                "destination_target": route.destination_target,
                "provider_config": route.provider_config,
                "semantic_text": semantic_text,
                POLICY_METADATA_KEY: metadata,
            },
        }
    }


def _build_route_step_specs(
    *,
    routes: list[CommunicationRoute],
    scope: str,
    owner_key: str,
    fallback: bool,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    events = FALLBACK_ROUTE_EVENTS if fallback else MATCHED_ROUTE_EVENTS
    for route in routes:
        for event_name, operation, run_phase, run_condition, base_step in events:
            specs.append(
                {
                    "task_key_template": _managed_task_key(
                        scope=scope,
                        owner_key=owner_key,
                        route_id=route.id,
                        event_name=event_name,
                    ),
                    "execution_target": route.execution_target,
                    "destination_target": route.destination_target,
                    "execution_engine": "bakery",
                    "execution_purpose": "comms",
                    "execution_payload": _managed_payload(
                        route=route,
                        scope=scope,
                        owner_key=owner_key,
                        event_name=event_name,
                    ),
                    "execution_parameters": {"operation": operation},
                    "is_default": True,
                    "is_blocking": False,
                    "expected_duration_sec": 15,
                    "timeout_duration_sec": 120,
                    "retry_count": 1,
                    "retry_delay": 5,
                    "on_failure": "continue",
                    "step_order": base_step + (route.position * 10),
                    "run_phase": run_phase,
                    "run_condition": run_condition,
                    "on_success": "continue",
                    "parallel_group": 0,
                    "depth": 0,
                    "execution_parameters_override": None,
                }
            )
    return specs


def build_recipe_local_policy_step_specs(
    *,
    recipe_id: int,
    routes: list[dict[str, Any]] | list[CommunicationRoute],
) -> tuple[list[CommunicationRoute], list[dict[str, Any]]]:
    normalized = normalize_routes(routes)
    return normalized, _build_route_step_specs(
        routes=normalized,
        scope="recipe",
        owner_key=str(recipe_id),
        fallback=False,
    )


async def _delete_recipe_ingredient_ids_safely(
    db: AsyncSession, *, recipe_ingredient_ids: list[int]
) -> None:
    if not recipe_ingredient_ids:
        return
    await db.execute(
        update(DishIngredient)
        .where(DishIngredient.recipe_ingredient_id.in_(recipe_ingredient_ids))
        .values(recipe_ingredient_id=None, updated_at=_now())
    )
    await db.execute(delete(RecipeIngredient).where(RecipeIngredient.id.in_(recipe_ingredient_ids)))


async def _cleanup_orphaned_managed_ingredients(
    db: AsyncSession, *, ingredient_ids: list[int]
) -> None:
    if not ingredient_ids:
        return
    result = await db.execute(
        select(Ingredient.id, func.count(RecipeIngredient.id))
        .outerjoin(RecipeIngredient, RecipeIngredient.ingredient_id == Ingredient.id)
        .where(Ingredient.id.in_(ingredient_ids))
        .group_by(Ingredient.id)
    )
    orphan_ids = [
        ingredient_id for ingredient_id, ref_count in result.all() if int(ref_count or 0) == 0
    ]
    if orphan_ids:
        await db.execute(delete(Ingredient).where(Ingredient.id.in_(orphan_ids)))


async def replace_recipe_communication_steps(
    db: AsyncSession,
    *,
    recipe: Recipe,
    step_specs: list[dict[str, Any]],
) -> None:
    comm_step_ids = [ri.id for ri in recipe.recipe_ingredients if is_communication_step(ri)]
    managed_ingredient_ids = [
        int(ri.ingredient_id)
        for ri in recipe.recipe_ingredients
        if is_managed_communications_ingredient(ri.ingredient)
    ]
    await _delete_recipe_ingredient_ids_safely(db, recipe_ingredient_ids=comm_step_ids)
    await _cleanup_orphaned_managed_ingredients(db, ingredient_ids=managed_ingredient_ids)

    now = _now()
    for spec in step_specs:
        ingredient = Ingredient(
            execution_target=spec["execution_target"],
            destination_target=spec["destination_target"],
            task_key_template=spec["task_key_template"],
            execution_engine=spec["execution_engine"],
            execution_purpose=spec["execution_purpose"],
            execution_payload=spec["execution_payload"],
            execution_parameters=spec["execution_parameters"],
            is_default=spec["is_default"],
            is_blocking=spec["is_blocking"],
            expected_duration_sec=spec["expected_duration_sec"],
            timeout_duration_sec=spec["timeout_duration_sec"],
            retry_count=spec["retry_count"],
            retry_delay=spec["retry_delay"],
            on_failure=spec["on_failure"],
            deleted=False,
            deleted_at=None,
            updated_at=now,
        )
        db.add(ingredient)
        await db.flush()

        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                step_order=spec["step_order"],
                on_success=spec["on_success"],
                parallel_group=spec["parallel_group"],
                depth=spec["depth"],
                execution_parameters_override=spec["execution_parameters_override"],
                run_phase=spec["run_phase"],
                run_condition=spec["run_condition"],
            )
        )


async def ensure_global_policy_recipe(db: AsyncSession) -> Recipe:
    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == MANAGED_RECIPE_NAME_GLOBAL)
        .with_for_update()
    )
    recipe = result.unique().scalars().first()
    now = _now()
    if recipe is None:
        recipe = Recipe(
            name=MANAGED_RECIPE_NAME_GLOBAL,
            description=f"{MANAGED_DESCRIPTION_GLOBAL} Global communications policy",
            enabled=True,
            clear_timeout_sec=None,
            deleted=False,
            deleted_at=None,
            updated_at=now,
            recipe_ingredients=[],
        )
        db.add(recipe)
        await db.flush()
    else:
        recipe.description = f"{MANAGED_DESCRIPTION_GLOBAL} Global communications policy"
        recipe.enabled = True
        recipe.deleted = False
        recipe.deleted_at = None
        recipe.updated_at = now
    return recipe


async def _load_global_policy_recipe(
    db: AsyncSession, *, for_update: bool = False
) -> Recipe | None:
    query = (
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == MANAGED_RECIPE_NAME_GLOBAL)
    )
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.unique().scalars().first()


def get_recipe_local_routes(recipe: Recipe | Any) -> list[CommunicationRoute]:
    return _group_routes_from_steps(
        [ri for ri in getattr(recipe, "recipe_ingredients", []) or [] if is_communication_step(ri)]
    )


def recipe_uses_local_communications(recipe: Recipe | Any) -> bool:
    return bool(get_recipe_local_routes(recipe))


def get_visible_recipe_steps(recipe: Recipe | Any) -> list[RecipeIngredient]:
    return [
        ri
        for ri in getattr(recipe, "recipe_ingredients", []) or []
        if not is_communication_step(ri)
    ]


async def get_global_policy_routes(db: AsyncSession) -> list[CommunicationRoute]:
    recipe = await _load_global_policy_recipe(db)
    if recipe is None:
        return []
    return _group_routes_from_steps(recipe.recipe_ingredients)


async def global_policy_configured(db: AsyncSession) -> bool:
    routes = await get_global_policy_routes(db)
    return any(route.enabled for route in routes)


async def get_effective_recipe_routes(
    db: AsyncSession, recipe: Recipe | Any
) -> tuple[str | None, list[CommunicationRoute]]:
    local_routes = get_recipe_local_routes(recipe)
    if any(route.enabled for route in local_routes):
        return "local", local_routes
    global_routes = await get_global_policy_routes(db)
    enabled_global = [route for route in global_routes if route.enabled]
    if enabled_global:
        return "global", global_routes
    return None, []


async def sync_global_policy_routes(
    db: AsyncSession,
    *,
    routes: list[dict[str, Any]] | list[CommunicationRoute],
) -> list[CommunicationRoute]:
    normalized = normalize_routes(routes)
    recipe = await ensure_global_policy_recipe(db)
    await replace_recipe_communication_steps(
        db,
        recipe=recipe,
        step_specs=_build_route_step_specs(
            routes=normalized,
            scope="global",
            owner_key="global",
            fallback=False,
        ),
    )
    recipe.updated_at = _now()
    return normalized


async def sync_recipe_local_policy(
    db: AsyncSession,
    *,
    recipe: Recipe,
    routes: list[dict[str, Any]] | list[CommunicationRoute],
) -> list[CommunicationRoute]:
    normalized = normalize_routes(routes)
    await replace_recipe_communication_steps(
        db,
        recipe=recipe,
        step_specs=_build_route_step_specs(
            routes=normalized,
            scope="recipe",
            owner_key=str(recipe.id),
            fallback=False,
        ),
    )
    recipe.updated_at = _now()
    return normalized


async def clear_recipe_local_policy(db: AsyncSession, *, recipe: Recipe) -> None:
    await replace_recipe_communication_steps(db, recipe=recipe, step_specs=[])
    recipe.updated_at = _now()


async def sync_fallback_policy_recipe(
    db: AsyncSession,
    *,
    routes: list[CommunicationRoute],
) -> Recipe | None:
    settings = get_settings()
    recipe_name = str(settings.catch_all_recipe_name or "").strip()
    if not recipe_name:
        return None

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == recipe_name)
        .with_for_update()
    )
    recipe = result.unique().scalars().first()
    now = _now()
    if recipe is None:
        recipe = Recipe(
            name=recipe_name,
            description=f"{MANAGED_DESCRIPTION_FALLBACK} Fallback communications policy",
            enabled=True,
            clear_timeout_sec=None,
            deleted=False,
            deleted_at=None,
            updated_at=now,
            recipe_ingredients=[],
        )
        db.add(recipe)
        await db.flush()
    else:
        recipe.description = f"{MANAGED_DESCRIPTION_FALLBACK} Fallback communications policy"
        recipe.deleted = False
        recipe.deleted_at = None
        recipe.updated_at = now

    enabled_routes = [route for route in routes if route.enabled]
    if not enabled_routes:
        recipe.enabled = False
        await replace_recipe_communication_steps(db, recipe=recipe, step_specs=[])
        return recipe

    recipe.enabled = True
    await replace_recipe_communication_steps(
        db,
        recipe=recipe,
        step_specs=_build_route_step_specs(
            routes=enabled_routes,
            scope="fallback",
            owner_key="fallback",
            fallback=True,
        ),
    )
    return recipe


async def get_global_policy_recipe_for_dispatch(db: AsyncSession) -> Recipe | None:
    recipe = await _load_global_policy_recipe(db)
    if recipe is None:
        return None
    routes = _group_routes_from_steps(recipe.recipe_ingredients)
    if not any(route.enabled for route in routes):
        return None
    return recipe


def _legacy_provider_config_from_payload(
    execution_target: str,
    execution_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = resolve_bakery_payload(execution_payload)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

    if isinstance(context.get("provider_config"), dict):
        return normalize_route_provider_config(
            execution_target,
            context.get("provider_config"),
            require_required=False,
        )

    legacy_sources: dict[str, dict[str, tuple[Any, ...]]] = {
        "rackspace_core": {
            "account_number": (
                payload.get("account_number"),
                context.get("account_number"),
                context.get("accountNumber"),
                context.get("coreAccountID"),
                context.get("rackspace_com_coreAccountID"),
            ),
            "queue": (
                payload.get("queue"),
                context.get("queue"),
                context.get("coreQueue"),
            ),
            "subcategory": (
                payload.get("subcategory"),
                context.get("subcategory"),
                context.get("coreSubcategory"),
            ),
            "source": (payload.get("source"), context.get("source")),
            "visibility": (payload.get("visibility"), context.get("visibility")),
        },
        "servicenow": {
            "urgency": (context.get("urgency"), context.get("serviceNowUrgency")),
            "impact": (context.get("impact"), context.get("serviceNowImpact")),
        },
        "jira": {
            "project_key": (context.get("project_key"), context.get("jiraProjectKey")),
            "issue_type": (context.get("issue_type"), context.get("jiraIssueType")),
            "transition_id": (context.get("transition_id"),),
        },
        "github": {
            "owner": (context.get("owner"), context.get("githubOwner")),
            "repo": (context.get("repo"), context.get("githubRepo")),
            "labels": (context.get("labels"), context.get("githubLabels")),
            "assignees": (context.get("assignees"), context.get("githubAssignees")),
        },
        "pagerduty": {
            "service_id": (context.get("service_id"), context.get("pagerDutyServiceId")),
            "from_email": (context.get("from_email"), context.get("pagerDutyFromEmail")),
            "urgency": (context.get("urgency"), context.get("pagerDutyUrgency")),
        },
    }

    seeded: dict[str, Any] = {}
    for key, candidates in legacy_sources.get(execution_target, {}).items():
        for value in candidates:
            if value not in (None, "", []):
                seeded[key] = value
                break

    settings = get_settings()
    if execution_target == "rackspace_core":
        default_queue = getattr(settings, "rackspace_core_default_queue", None)
        default_subcategory = getattr(settings, "rackspace_core_default_subcategory", None)
        if default_queue:
            seeded.setdefault("queue", default_queue)
        if default_subcategory:
            seeded.setdefault("subcategory", default_subcategory)

    return normalize_route_provider_config(
        execution_target,
        seeded,
        require_required=False,
    )


def _group_routes_from_steps(steps: list[RecipeIngredient]) -> list[CommunicationRoute]:
    grouped: dict[str, CommunicationRoute] = {}
    for step in steps:
        ingredient = step.ingredient
        if ingredient is None or not is_communication_ingredient(ingredient):
            continue
        metadata = _metadata_from_payload(ingredient.execution_payload)
        route: CommunicationRoute | None = None
        if metadata:
            route = _route_from_metadata(metadata)
        if route is None:
            execution_target = normalize_destination_type(
                getattr(ingredient, "execution_target", "")
            )
            destination_target = normalize_destination_target(
                getattr(ingredient, "destination_target", "")
            )
            route = CommunicationRoute(
                id=f"legacy-{_slug(execution_target)}-{_slug(destination_target or 'default')}",
                label=titleize_route(
                    execution_target,
                    destination_target or getattr(ingredient, "task_key_template", ""),
                ),
                execution_target=execution_target,
                destination_target=destination_target,
                provider_config=_legacy_provider_config_from_payload(
                    execution_target,
                    getattr(ingredient, "execution_payload", None),
                ),
                enabled=True,
                position=len(grouped) + 1,
            )
        route.provider_config = normalize_route_provider_config(
            route.execution_target,
            route.provider_config,
            require_required=False,
        )
        grouped[route.id] = route
    return sorted(grouped.values(), key=lambda item: (item.position, item.label.lower()))


def serialize_route(route: CommunicationRoute) -> dict[str, Any]:
    return {
        "id": route.id,
        "label": route.label,
        "execution_target": route.execution_target,
        "destination_target": route.destination_target,
        "provider_config": route.provider_config,
        "enabled": route.enabled,
        "position": route.position,
    }


def lifecycle_summary() -> dict[str, str]:
    return {
        "success": "When an alert clears after successful auto-remediation, PoundCake opens and then closes each configured route.",
        "failure_or_escalation": "When remediation fails or escalation is needed, PoundCake opens each configured route and leaves it open.",
        "unmatched_alert": "When no matching workflow exists, PoundCake opens each configured fallback route immediately.",
        "clear_after_escalation": "When an escalated alert later clears, PoundCake notifies the existing route and leaves it open.",
    }


def route_payloads_for_response(
    *,
    mode: str,
    effective_source: str | None,
    routes: list[CommunicationRoute],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "effective_source": effective_source,
        "routes": [serialize_route(route) for route in routes],
    }


def policy_has_enabled_routes(routes: list[CommunicationRoute]) -> bool:
    return any(route.enabled for route in routes)


def should_seed_route_step(
    *,
    recipe_ingredient: RecipeIngredient | Any,
    order: Any,
) -> bool:
    ingredient = getattr(recipe_ingredient, "ingredient", None)
    if ingredient is None:
        return True
    params = getattr(ingredient, "execution_parameters", None) or {}
    operation = str(params.get("operation") or "").strip().lower()
    run_condition = str(getattr(recipe_ingredient, "run_condition", "") or "").strip().lower()
    if operation != "notify":
        return True
    if run_condition not in {
        "resolved_after_failure",
        "resolved_after_timeout",
        "resolved_after_no_remediation",
    }:
        return True
    metadata = _metadata_from_payload(getattr(ingredient, "execution_payload", None))
    execution_target = metadata.get("execution_target") or getattr(
        ingredient, "execution_target", ""
    )
    destination_target = metadata.get("destination_target") or getattr(
        ingredient, "destination_target", ""
    )
    return is_route_available_for_update(
        order=order,
        execution_target=str(execution_target),
        destination_target=str(destination_target),
    )

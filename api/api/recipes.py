#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for recipe management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.schemas.query_params import RecipeQueryParams, validate_query_params
from api.schemas.schemas import DeleteResponse, RecipeCreate, RecipeDetailResponse, RecipeUpdate
from api.services.communications_policy import (
    build_recipe_local_policy_step_specs,
    get_global_policy_routes,
    get_recipe_local_routes,
    get_visible_recipe_steps,
    global_policy_configured,
    is_communication_step,
    is_hidden_workflow_recipe,
    normalize_routes,
    policy_has_enabled_routes,
    route_payloads_for_response,
)
from api.services.bakery_monitor import mark_route_catalog_dirty, sync_monitor_route_catalog
from api.services.recipe_ingredient_cleanup import delete_recipe_ingredients_safely

router = APIRouter()
logger = get_logger(__name__)


def _recipe_query():
    return select(Recipe).options(
        joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient)
    )


def _recipe_to_step_spec(step: RecipeIngredient) -> dict[str, Any]:
    return {
        "ingredient_id": step.ingredient_id,
        "step_order": step.step_order,
        "on_success": step.on_success,
        "parallel_group": step.parallel_group,
        "depth": step.depth,
        "execution_parameters_override": step.execution_parameters_override,
        "run_phase": step.run_phase,
        "run_condition": step.run_condition,
    }


def _recipe_ingredient_row(
    *,
    recipe_id: int,
    spec: dict[str, Any],
    ingredient_id: int | None = None,
) -> RecipeIngredient:
    resolved_ingredient_id = ingredient_id or spec.get("ingredient_id")
    if resolved_ingredient_id is None:
        raise KeyError("ingredient_id")
    return RecipeIngredient(
        recipe_id=recipe_id,
        ingredient_id=resolved_ingredient_id,
        step_order=spec["step_order"],
        on_success=spec["on_success"],
        parallel_group=spec["parallel_group"],
        depth=spec["depth"],
        execution_parameters_override=spec["execution_parameters_override"],
        run_phase=spec["run_phase"],
        run_condition=spec["run_condition"],
    )


def _queue_recipe_steps(
    db: AsyncSession, *, recipe_id: int, step_specs: list[dict[str, Any]]
) -> None:
    for spec in step_specs:
        db.add(_recipe_ingredient_row(recipe_id=recipe_id, spec=spec))


async def _validate_ingredient_ids(db: AsyncSession, *, step_specs: list[dict[str, Any]]) -> None:
    ingredient_ids = [int(item["ingredient_id"]) for item in step_specs]
    if not ingredient_ids:
        return
    result = await db.execute(select(Ingredient).where(Ingredient.id.in_(ingredient_ids)))
    found_ids = {ingredient.id for ingredient in result.scalars().all()}
    missing = [ingredient_id for ingredient_id in ingredient_ids if ingredient_id not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Missing ingredients: {missing}")


async def _serialize_recipe(db: AsyncSession, recipe: Recipe) -> dict[str, Any]:
    visible_steps = get_visible_recipe_steps(recipe)
    local_routes = get_recipe_local_routes(recipe)
    if local_routes:
        communications = route_payloads_for_response(
            mode="local",
            effective_source="local" if policy_has_enabled_routes(local_routes) else None,
            routes=local_routes,
        )
    else:
        global_routes = await get_global_policy_routes(db)
        communications = route_payloads_for_response(
            mode="inherit",
            effective_source="global" if policy_has_enabled_routes(global_routes) else None,
            routes=global_routes,
        )

    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "enabled": recipe.enabled,
        "clear_timeout_sec": recipe.clear_timeout_sec,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "deleted": recipe.deleted,
        "deleted_at": recipe.deleted_at,
        "recipe_ingredients": visible_steps,
        "communications": communications,
    }


async def _validate_effective_communications(
    db: AsyncSession,
    *,
    enabled: bool,
    communications_mode: str,
    local_routes: list[Any],
) -> None:
    if not enabled:
        return
    if communications_mode == "local":
        if not policy_has_enabled_routes(local_routes):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Enabled workflows must define at least one enabled workflow-specific "
                    "communication route when using local communications."
                ),
            )
        return

    if not await global_policy_configured(db):
        raise HTTPException(
            status_code=400,
            detail=(
                "Enabled workflows must inherit a configured global communications policy "
                "or define workflow-specific communications."
            ),
        )


def _communications_payload_mode(payload: RecipeCreate | RecipeUpdate | None) -> str | None:
    if payload is None:
        return None
    communications = getattr(payload, "communications", None)
    if communications is None:
        return None
    return communications.mode


def _communications_payload_routes(
    payload: RecipeCreate | RecipeUpdate | None,
) -> list[dict[str, Any]] | None:
    if payload is None:
        return None
    communications = getattr(payload, "communications", None)
    if communications is None:
        return None
    return [item.model_dump() for item in communications.routes]


def _step_specs_from_payload(step_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ingredient_id": item["ingredient_id"],
            "step_order": item["step_order"],
            "on_success": item.get("on_success", "continue"),
            "parallel_group": item.get("parallel_group", 0),
            "depth": item.get("depth", 0),
            "execution_parameters_override": item.get("execution_parameters_override"),
            "run_phase": item.get("run_phase", "both"),
            "run_condition": item.get("run_condition", "always"),
        }
        for item in step_items
    ]


@router.post("/recipes/", response_model=RecipeDetailResponse, status_code=201)
async def create_recipe(
    request: Request, recipe: RecipeCreate, db: AsyncSession = Depends(get_db)
) -> RecipeDetailResponse:
    """Create a new recipe with remediation/utility steps and optional local comms."""
    req_id = request.state.req_id
    logger.info("Creating recipe", extra={"req_id": req_id, "recipe_name": recipe.name})

    visible_step_specs = _step_specs_from_payload(
        [item.model_dump() for item in recipe.recipe_ingredients]
    )
    communications_mode = recipe.communications.mode
    local_routes = normalize_routes(_communications_payload_routes(recipe) or [])

    async with db.begin():
        await _validate_ingredient_ids(db, step_specs=visible_step_specs)
        await _validate_effective_communications(
            db,
            enabled=recipe.enabled,
            communications_mode=communications_mode,
            local_routes=local_routes,
        )
        result = await db.execute(select(Recipe).where(Recipe.name == recipe.name))
        existing = result.scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Recipe '{recipe.name}' already exists")

        db_recipe = Recipe(
            name=recipe.name,
            description=recipe.description,
            enabled=recipe.enabled,
            clear_timeout_sec=recipe.clear_timeout_sec,
        )
        db.add(db_recipe)
        await db.flush()

        _queue_recipe_steps(db, recipe_id=db_recipe.id, step_specs=visible_step_specs)
        if communications_mode == "local":
            _, managed_specs = build_recipe_local_policy_step_specs(
                recipe_id=db_recipe.id,
                routes=local_routes,
            )
            for spec in managed_specs:
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
                )
                db.add(ingredient)
                await db.flush()
                db.add(
                    _recipe_ingredient_row(
                        recipe_id=db_recipe.id,
                        spec=spec,
                        ingredient_id=ingredient.id,
                    )
                )

    result = await db.execute(_recipe_query().where(Recipe.name == recipe.name))
    db_recipe = result.unique().scalars().first()
    if db_recipe is None:
        raise HTTPException(status_code=500, detail="Recipe retrieval failed after create")
    try:
        await sync_monitor_route_catalog(force=True)
    except Exception as exc:  # noqa: BLE001
        await mark_route_catalog_dirty()
        logger.warning(
            "Failed to refresh Bakery monitor route catalog after recipe create",
            extra={"req_id": req_id, "recipe_name": recipe.name, "error": str(exc)},
        )
    return await _serialize_recipe(db, db_recipe)


@router.get("/recipes/", response_model=List[RecipeDetailResponse])
async def list_recipes(
    request: Request,
    params: RecipeQueryParams = Depends(validate_query_params(RecipeQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """List user-facing workflows with communications summary."""
    _ = request.state.req_id
    query = _recipe_query()
    if params.name is not None:
        query = query.where(Recipe.name == params.name)
    if params.enabled is not None:
        query = query.where(Recipe.enabled == params.enabled)
    query = query.limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    recipes = [
        recipe
        for recipe in result.unique().scalars().all()
        if not is_hidden_workflow_recipe(recipe)
    ]
    return [await _serialize_recipe(db, recipe) for recipe in recipes]


@router.get("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def get_recipe(recipe_id: int, db: AsyncSession = Depends(get_db)):
    """Get a workflow with non-communications steps and effective communications settings."""
    result = await db.execute(_recipe_query().where(Recipe.id == recipe_id))
    recipe = result.unique().scalars().first()
    if not recipe or is_hidden_workflow_recipe(recipe):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return await _serialize_recipe(db, recipe)


@router.get("/recipes/by-name/{recipe_name}", response_model=RecipeDetailResponse)
async def get_recipe_by_name(recipe_name: str, db: AsyncSession = Depends(get_db)):
    """Get a workflow by name."""
    result = await db.execute(_recipe_query().where(Recipe.name == recipe_name))
    recipe = result.unique().scalars().first()
    if not recipe or is_hidden_workflow_recipe(recipe):
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")
    return await _serialize_recipe(db, recipe)


@router.delete("/recipes/{recipe_id}", response_model=DeleteResponse)
async def delete_recipe(
    request: Request, recipe_id: int, db: AsyncSession = Depends(get_db)
) -> DeleteResponse:
    """Delete a recipe and its recipe_ingredients."""
    req_id = request.state.req_id
    logger.info("Deleting recipe", extra={"req_id": req_id, "recipe_id": recipe_id})

    async with db.begin():
        result = await db.execute(select(Recipe).where(Recipe.id == recipe_id).with_for_update())
        recipe = result.unique().scalars().first()
        if not recipe or is_hidden_workflow_recipe(recipe):
            raise HTTPException(status_code=404, detail="Recipe not found")
        recipe_name = recipe.name
        await delete_recipe_ingredients_safely(db, recipe_id=recipe.id)
        await db.delete(recipe)
    try:
        await sync_monitor_route_catalog(force=True)
    except Exception as exc:  # noqa: BLE001
        await mark_route_catalog_dirty()
        logger.warning(
            "Failed to refresh Bakery monitor route catalog after recipe delete",
            extra={"req_id": req_id, "recipe_id": recipe_id, "error": str(exc)},
        )

    return DeleteResponse(
        status="deleted", id=recipe_id, message=f"Recipe '{recipe_name}' deleted successfully"
    )


@router.put("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
@router.patch("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def update_recipe(
    request: Request,
    recipe_id: int,
    payload: RecipeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a workflow, preserving comms when omitted and normalizing local comms when supplied."""
    req_id = request.state.req_id
    recipe: Recipe | None = None
    async with db.begin():
        result = await db.execute(_recipe_query().where(Recipe.id == recipe_id).with_for_update())
        recipe = result.unique().scalars().first()
        if not recipe or is_hidden_workflow_recipe(recipe):
            raise HTTPException(status_code=404, detail="Recipe not found")

        existing_visible_specs = [
            _recipe_to_step_spec(step) for step in get_visible_recipe_steps(recipe)
        ]
        existing_comm_specs = [
            _recipe_to_step_spec(step)
            for step in recipe.recipe_ingredients
            if is_communication_step(step)
        ]
        current_local_routes = get_recipe_local_routes(recipe)

        update_data = payload.model_dump(exclude_unset=True)
        recipe_ingredients = update_data.pop("recipe_ingredients", None)
        communications = update_data.pop("communications", None)
        for key, value in update_data.items():
            setattr(recipe, key, value)

        final_visible_specs = existing_visible_specs
        if recipe_ingredients is not None:
            final_visible_specs = _step_specs_from_payload(recipe_ingredients)
            await _validate_ingredient_ids(db, step_specs=final_visible_specs)

        final_communications_mode = "local" if current_local_routes else "inherit"
        final_local_routes = current_local_routes
        final_comm_specs = existing_comm_specs
        if communications is not None:
            final_communications_mode = communications["mode"]
            if final_communications_mode == "local":
                final_local_routes, managed_specs = build_recipe_local_policy_step_specs(
                    recipe_id=recipe.id,
                    routes=communications["routes"],
                )
                final_comm_specs = [
                    {
                        "managed_spec": spec,
                    }
                    for spec in managed_specs
                ]
            else:
                final_local_routes = []
                final_comm_specs = []

        await _validate_effective_communications(
            db,
            enabled=bool(recipe.enabled),
            communications_mode=final_communications_mode,
            local_routes=final_local_routes,
        )

        if recipe_ingredients is not None or communications is not None:
            await delete_recipe_ingredients_safely(db, recipe_id=recipe.id)
            recipe.recipe_ingredients = []
            _queue_recipe_steps(db, recipe_id=recipe.id, step_specs=final_visible_specs)
            for spec in final_comm_specs:
                if "managed_spec" in spec:
                    managed = spec["managed_spec"]
                    ingredient = Ingredient(
                        execution_target=managed["execution_target"],
                        destination_target=managed["destination_target"],
                        task_key_template=managed["task_key_template"],
                        execution_engine=managed["execution_engine"],
                        execution_purpose=managed["execution_purpose"],
                        execution_payload=managed["execution_payload"],
                        execution_parameters=managed["execution_parameters"],
                        is_default=managed["is_default"],
                        is_blocking=managed["is_blocking"],
                        expected_duration_sec=managed["expected_duration_sec"],
                        timeout_duration_sec=managed["timeout_duration_sec"],
                        retry_count=managed["retry_count"],
                        retry_delay=managed["retry_delay"],
                        on_failure=managed["on_failure"],
                    )
                    db.add(ingredient)
                    await db.flush()
                    db.add(
                        _recipe_ingredient_row(
                            recipe_id=recipe.id,
                            spec=managed,
                            ingredient_id=ingredient.id,
                        )
                    )
                    continue
                db.add(_recipe_ingredient_row(recipe_id=recipe.id, spec=spec))
            await db.flush()

        recipe.updated_at = datetime.now(timezone.utc)

    if recipe is None:
        raise HTTPException(status_code=500, detail="Recipe update failed")

    result = await db.execute(
        _recipe_query().where(Recipe.id == recipe_id).execution_options(populate_existing=True)
    )
    updated_recipe = result.unique().scalars().first()
    if updated_recipe is None:
        raise HTTPException(status_code=500, detail="Recipe update failed")
    try:
        await sync_monitor_route_catalog(force=True)
    except Exception as exc:  # noqa: BLE001
        await mark_route_catalog_dirty()
        logger.warning(
            "Failed to refresh Bakery monitor route catalog after recipe update",
            extra={"req_id": req_id, "recipe_id": recipe_id, "error": str(exc)},
        )
    return await _serialize_recipe(db, updated_recipe)

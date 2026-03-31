#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for ingredient management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import not_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.schemas.schemas import (
    IngredientCreate,
    IngredientUpdate,
    IngredientResponse,
    DeleteResponse,
)
from api.schemas.query_params import IngredientQueryParams, validate_query_params
from api.services.communications_policy import (
    MANAGED_TASK_PREFIX,
    is_managed_communications_ingredient,
)

router = APIRouter()
logger = get_logger(__name__)


@router.post("/ingredients/", response_model=IngredientResponse, status_code=201)
async def create_ingredient(
    request: Request, ingredient: IngredientCreate, db: AsyncSession = Depends(get_db)
) -> IngredientResponse:
    """Create a new global ingredient."""
    req_id = request.state.req_id

    logger.info(
        "Creating ingredient",
        extra={"req_id": req_id, "execution_target": ingredient.execution_target},
    )

    result = await db.execute(
        select(Ingredient).where(
            Ingredient.execution_target == ingredient.execution_target,
            Ingredient.destination_target == (ingredient.destination_target or ""),
            Ingredient.task_key_template == ingredient.task_key_template,
            Ingredient.execution_engine == ingredient.execution_engine,
        )
    )
    existing = result.scalars().first()
    if existing:
        logger.warning(
            "Ingredient already exists",
            extra={
                "req_id": req_id,
                "execution_target": ingredient.execution_target,
                "existing_id": existing.id,
            },
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Ingredient with execution_target "
                f"'{ingredient.execution_target}' and task_key_template "
                f"'{ingredient.task_key_template}' already exists for engine "
                f"'{ingredient.execution_engine}'"
            ),
        )

    db_ingredient = Ingredient(
        execution_target=ingredient.execution_target,
        destination_target=ingredient.destination_target or "",
        task_key_template=ingredient.task_key_template,
        execution_id=ingredient.execution_id,
        execution_payload=ingredient.execution_payload,
        execution_parameters=ingredient.execution_parameters,
        is_default=ingredient.is_default,
        is_active=ingredient.is_active,
        execution_engine=ingredient.execution_engine,
        execution_purpose=ingredient.execution_purpose,
        is_blocking=ingredient.is_blocking,
        expected_duration_sec=ingredient.expected_duration_sec,
        timeout_duration_sec=ingredient.timeout_duration_sec,
        retry_count=ingredient.retry_count,
        retry_delay=ingredient.retry_delay,
        on_failure=ingredient.on_failure,
    )
    db.add(db_ingredient)
    await db.commit()
    await db.refresh(db_ingredient)

    return db_ingredient


@router.get("/ingredients/", response_model=List[IngredientResponse])
async def list_ingredients(
    params: IngredientQueryParams = Depends(validate_query_params(IngredientQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """List global ingredients with optional filtering."""
    query = select(Ingredient)
    query = query.where(not_(Ingredient.task_key_template.like(f"{MANAGED_TASK_PREFIX}%")))

    if params.execution_target is not None:
        query = query.where(Ingredient.execution_target == params.execution_target)
    if params.task_key_template is not None:
        query = query.where(Ingredient.task_key_template == params.task_key_template)

    query = query.limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def get_ingredient(ingredient_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch a single ingredient by ID."""
    result = await db.execute(select(Ingredient).where(Ingredient.id == ingredient_id))
    ingredient = result.scalars().first()
    if not ingredient or is_managed_communications_ingredient(ingredient):
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient


@router.delete("/ingredients/{ingredient_id}", response_model=DeleteResponse)
async def delete_ingredient(
    request: Request, ingredient_id: int, db: AsyncSession = Depends(get_db)
) -> DeleteResponse:
    """Delete a global ingredient."""
    req_id = request.state.req_id
    async with db.begin():
        result = await db.execute(
            select(Ingredient).where(Ingredient.id == ingredient_id).with_for_update()
        )
        ingredient = result.scalars().first()
        if not ingredient or is_managed_communications_ingredient(ingredient):
            raise HTTPException(status_code=404, detail="Ingredient not found")

        task_name = ingredient.task_key_template
        await db.delete(ingredient)

    logger.info(
        "Ingredient deleted",
        extra={"req_id": req_id, "ingredient_id": ingredient_id, "task_name": task_name},
    )

    return DeleteResponse(
        status="deleted",
        id=ingredient_id,
        message=f"Ingredient '{task_name}' deleted successfully",
    )


@router.get("/ingredients/by-name/{recipe_name}", response_model=List[IngredientResponse])
async def get_ingredients_by_recipe_name(recipe_name: str, db: AsyncSession = Depends(get_db)):
    """List ingredients for a recipe name, ordered by step_order."""
    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == recipe_name)
    )
    recipe = result.unique().scalars().first()
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")

    return [ri.ingredient for ri in recipe.recipe_ingredients if ri.ingredient is not None]


@router.get("/ingredients/by-recipe/{recipe_id}", response_model=List[IngredientResponse])
async def get_ingredients_by_recipe_id(recipe_id: int, db: AsyncSession = Depends(get_db)):
    """List ingredients for a recipe ID, ordered by step_order."""
    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.id == recipe_id)
    )
    recipe = result.unique().scalars().first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return [ri.ingredient for ri in recipe.recipe_ingredients if ri.ingredient is not None]


@router.patch("/ingredients/{ingredient_id}", response_model=IngredientResponse)
@router.put("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def update_ingredient(
    ingredient_id: int, payload: IngredientUpdate, db: AsyncSession = Depends(get_db)
) -> IngredientResponse:
    """Retire a global ingredient without mutating its execution template."""
    ingredient: Ingredient | None = None
    async with db.begin():
        result = await db.execute(
            select(Ingredient).where(Ingredient.id == ingredient_id).with_for_update()
        )
        ingredient = result.scalars().first()
        if not ingredient or is_managed_communications_ingredient(ingredient):
            raise HTTPException(status_code=404, detail="Ingredient not found")

        update_data = payload.model_dump(exclude_unset=True)
        allowed_keys = {"is_active"}
        if set(update_data) - allowed_keys:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ingredients are immutable after creation. Create a replacement ingredient and "
                    "retire the old one with is_active=false."
                ),
            )
        if update_data.get("is_active") is not False:
            raise HTTPException(
                status_code=409,
                detail="Only retirement updates with is_active=false are allowed for ingredients",
            )
        if "destination_target" in update_data and update_data["destination_target"] is None:
            update_data["destination_target"] = ""
        for key, value in update_data.items():
            setattr(ingredient, key, value)

        setattr(ingredient, "updated_at", datetime.now(timezone.utc))

    if ingredient is None:
        raise HTTPException(status_code=500, detail="Ingredient update failed")
    await db.refresh(ingredient)

    return ingredient

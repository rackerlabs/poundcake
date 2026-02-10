#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for recipe management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime, timezone

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Recipe, RecipeIngredient, Ingredient
from api.schemas.schemas import (
    RecipeCreate,
    RecipeUpdate,
    RecipeDetailResponse,
    DeleteResponse,
)
from api.schemas.query_params import RecipeQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)


@router.post("/recipes/", response_model=RecipeDetailResponse, status_code=201)
async def create_recipe(
    request: Request, recipe: RecipeCreate, db: AsyncSession = Depends(get_db)
) -> RecipeDetailResponse:
    """Create a new recipe with recipe_ingredients."""
    req_id = request.state.req_id

    logger.info("Creating recipe", extra={"req_id": req_id, "recipe_name": recipe.name})

    result = await db.execute(select(Recipe).where(Recipe.name == recipe.name))
    existing = result.scalars().first()
    if existing:
        logger.warning(
            "Recipe already exists",
            extra={"req_id": req_id, "recipe_name": recipe.name},
        )
        raise HTTPException(status_code=400, detail=f"Recipe '{recipe.name}' already exists")

    db_recipe = Recipe(
        name=recipe.name,
        description=recipe.description,
        enabled=recipe.enabled,
        workflow_id=recipe.workflow_id,
        workflow_payload=recipe.workflow_payload,
        workflow_parameters=recipe.workflow_parameters,
    )
    db.add(db_recipe)
    await db.flush()

    ingredient_ids = [ri.ingredient_id for ri in recipe.recipe_ingredients]
    if ingredient_ids:
        result = await db.execute(select(Ingredient).where(Ingredient.id.in_(ingredient_ids)))
        ingredients = result.scalars().all()
    else:
        ingredients = []
    found_ids = {ing.id for ing in ingredients}
    missing = [ing_id for ing_id in ingredient_ids if ing_id not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Missing ingredients: {missing}")

    for ri in recipe.recipe_ingredients:
        db_recipe_ingredient = RecipeIngredient(
            recipe_id=db_recipe.id,
            ingredient_id=ri.ingredient_id,
            step_order=ri.step_order,
            on_success=ri.on_success,
        )
        db.add(db_recipe_ingredient)

    await db.commit()

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.id == db_recipe.id)
    )
    db_recipe = result.scalars().first()

    logger.info(
        "Recipe created successfully",
        extra={
            "req_id": req_id,
            "recipe_id": db_recipe.id,
            "recipe_name": db_recipe.name,
            "ingredient_count": len(recipe.recipe_ingredients),
        },
    )

    return db_recipe


@router.get("/recipes/", response_model=List[RecipeDetailResponse])
async def list_recipes(
    request: Request,
    params: RecipeQueryParams = Depends(validate_query_params(RecipeQueryParams)),
    db: AsyncSession = Depends(get_db),
):
    """
    List recipes with optional filtering and nested recipe_ingredients.

    Query Parameters:
    - name: Filter by recipe name
    - enabled: Filter by enabled status (true/false)
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    query = select(Recipe).options(
        joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient)
    )

    if params.name is not None:
        query = query.where(Recipe.name == params.name)
    if params.enabled is not None:
        query = query.where(Recipe.enabled == params.enabled)

    query = query.limit(params.limit).offset(params.offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def get_recipe(recipe_id: int, db: AsyncSession = Depends(get_db)):
    """Get a recipe with all its recipe_ingredients."""
    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.id == recipe_id)
    )
    recipe = result.scalars().first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return recipe


@router.get("/recipes/by-name/{recipe_name}", response_model=RecipeDetailResponse)
async def get_recipe_by_name(recipe_name: str, db: AsyncSession = Depends(get_db)):
    """Get a recipe by name (matches order.alert_group_name)."""
    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.name == recipe_name)
    )
    recipe = result.scalars().first()
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")

    return recipe


@router.delete("/recipes/{recipe_id}", response_model=DeleteResponse)
async def delete_recipe(
    request: Request, recipe_id: int, db: AsyncSession = Depends(get_db)
) -> DeleteResponse:
    """Delete a recipe and its recipe_ingredients."""
    req_id = request.state.req_id

    logger.info("Deleting recipe", extra={"req_id": req_id, "recipe_id": recipe_id})

    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalars().first()
    if not recipe:
        logger.warning("Recipe not found", extra={"req_id": req_id, "recipe_id": recipe_id})
        raise HTTPException(status_code=404, detail="Recipe not found")

    recipe_name = recipe.name
    await db.delete(recipe)
    await db.commit()

    logger.info(
        "Recipe deleted successfully",
        extra={"req_id": req_id, "recipe_id": recipe_id, "recipe_name": recipe_name},
    )

    return DeleteResponse(
        status="deleted", id=recipe_id, message=f"Recipe '{recipe_name}' deleted successfully"
    )


@router.put("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
@router.patch("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def update_recipe(recipe_id: int, payload: RecipeUpdate, db: AsyncSession = Depends(get_db)):
    """Update a recipe (used to store workflow_id/payload/parameters)."""
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalars().first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(recipe, key, value)
    recipe.updated_at = datetime.now(timezone.utc)

    await db.commit()

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.id == recipe_id)
    )
    recipe = result.scalars().first()

    return recipe

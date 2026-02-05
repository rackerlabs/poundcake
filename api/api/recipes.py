#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for recipe and ingredient management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
from typing import List

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Recipe, Ingredient
from api.schemas.schemas import (
    RecipeCreate,
    RecipeDetailResponse,
    IngredientResponse,
    DeleteResponse,
)
from api.schemas.query_params import RecipeQueryParams, validate_query_params

router = APIRouter()
logger = get_logger(__name__)

# --- Recipe Endpoints ---


@router.post("/recipes/", response_model=RecipeDetailResponse, status_code=201)
async def create_recipe(
    request: Request, recipe: RecipeCreate, db: Session = Depends(get_db)
) -> RecipeDetailResponse:
    """Create a new recipe with ingredients."""
    req_id = request.state.req_id

    logger.info(
        "create_recipe: Creating recipe", extra={"req_id": req_id, "recipe_name": recipe.name}
    )

    existing = db.query(Recipe).filter(Recipe.name == recipe.name).first()
    if existing:
        logger.warning(
            "create_recipe: Recipe already exists",
            extra={"req_id": req_id, "recipe_name": recipe.name},
        )
        raise HTTPException(status_code=400, detail=f"Recipe '{recipe.name}' already exists")

    db_recipe = Recipe(name=recipe.name, description=recipe.description, enabled=recipe.enabled)
    db.add(db_recipe)
    db.flush()  # Get the ID before adding ingredients

    for ingredient_data in recipe.ingredients:
        db_ingredient = Ingredient(
            recipe_id=db_recipe.id,
            task_id=ingredient_data.task_id,
            task_name=ingredient_data.task_name,
            task_order=ingredient_data.task_order,
            is_blocking=ingredient_data.is_blocking,
            st2_action=ingredient_data.st2_action,
            parameters=ingredient_data.parameters,
            expected_time_to_completion=ingredient_data.expected_time_to_completion,
            timeout=ingredient_data.timeout,
            retry_count=ingredient_data.retry_count,
            retry_delay=ingredient_data.retry_delay,
            on_failure=ingredient_data.on_failure,
        )
        db.add(db_ingredient)

    db.commit()
    db.refresh(db_recipe)

    logger.info(
        "create_recipe: Recipe created successfully",
        extra={
            "req_id": req_id,
            "recipe_id": db_recipe.id,
            "recipe_name": db_recipe.name,
            "ingredient_count": len(recipe.ingredients),
        },
    )

    return db_recipe


@router.get("/recipes/", response_model=List[RecipeDetailResponse])
async def list_recipes(
    request: Request,
    params: RecipeQueryParams = Depends(validate_query_params(RecipeQueryParams)),
    db: Session = Depends(get_db),
):
    """
    List recipes with optional filtering and nested ingredients.

    Query Parameters:
    - name: Filter by recipe name
    - enabled: Filter by enabled status (true/false)
    - limit: Maximum number of results (default: 100, max: 1000)
    - offset: Number of results to skip (default: 0)

    Returns 422 Unprocessable Entity if unknown or invalid query parameters are provided.
    """
    query = db.query(Recipe).options(joinedload(Recipe.ingredients))

    if params.name is not None:
        query = query.filter(Recipe.name == params.name)
    if params.enabled is not None:
        query = query.filter(Recipe.enabled == params.enabled)

    return query.limit(params.limit).offset(params.offset).all()


@router.get("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Get a recipe with all its ingredients."""
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.ingredients))
        .filter(Recipe.id == recipe_id)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return recipe


@router.get("/recipes/by-name/{recipe_name}", response_model=RecipeDetailResponse)
async def get_recipe_by_name(recipe_name: str, db: Session = Depends(get_db)):
    """Get a recipe by name (matches alert.group_name)."""
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.ingredients))
        .filter(Recipe.name == recipe_name)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")

    return recipe


@router.delete("/recipes/{recipe_id}", response_model=DeleteResponse)
async def delete_recipe(
    request: Request, recipe_id: int, db: Session = Depends(get_db)
) -> DeleteResponse:
    """Delete a recipe and all its ingredients."""
    req_id = request.state.req_id

    logger.info("delete_recipe: Deleting recipe", extra={"req_id": req_id, "recipe_id": recipe_id})

    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        logger.warning(
            "delete_recipe: Recipe not found", extra={"req_id": req_id, "recipe_id": recipe_id}
        )
        raise HTTPException(status_code=404, detail="Recipe not found")

    recipe_name = recipe.name
    db.delete(recipe)
    db.commit()

    logger.info(
        "delete_recipe: Recipe deleted successfully",
        extra={"req_id": req_id, "recipe_id": recipe_id, "recipe_name": recipe_name},
    )

    return DeleteResponse(
        status="deleted", id=recipe_id, message=f"Recipe '{recipe_name}' deleted successfully"
    )


# --- Ingredient Endpoints ---


@router.get("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def get_ingredient(ingredient_id: int, db: Session = Depends(get_db)):
    """
    Fetch a single ingredient.
    Crucial for oven-executor (oven.py) to resolve task details.
    """
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient

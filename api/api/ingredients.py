#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for ingredient management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
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

router = APIRouter()
logger = get_logger(__name__)


@router.post("/ingredients/", response_model=IngredientResponse, status_code=201)
async def create_ingredient(
    request: Request, ingredient: IngredientCreate, db: Session = Depends(get_db)
) -> IngredientResponse:
    """Create a new global ingredient."""
    req_id = request.state.req_id

    logger.info("Creating ingredient", extra={"req_id": req_id, "task_id": ingredient.task_id})

    db_ingredient = Ingredient(
        task_id=ingredient.task_id,
        task_name=ingredient.task_name,
        action_id=ingredient.action_id,
        action_payload=ingredient.action_payload,
        action_parameters=ingredient.action_parameters,
        is_blocking=ingredient.is_blocking,
        expected_duration_sec=ingredient.expected_duration_sec,
        timeout_duration_sec=ingredient.timeout_duration_sec,
        retry_count=ingredient.retry_count,
        retry_delay=ingredient.retry_delay,
        on_failure=ingredient.on_failure,
    )
    db.add(db_ingredient)
    db.commit()
    db.refresh(db_ingredient)

    return db_ingredient


@router.get("/ingredients/", response_model=List[IngredientResponse])
async def list_ingredients(
    params: IngredientQueryParams = Depends(validate_query_params(IngredientQueryParams)),
    db: Session = Depends(get_db),
):
    """List global ingredients with optional filtering."""
    query = db.query(Ingredient)

    if params.task_id is not None:
        query = query.filter(Ingredient.task_id == params.task_id)
    if params.task_name is not None:
        query = query.filter(Ingredient.task_name == params.task_name)

    return query.limit(params.limit).offset(params.offset).all()


@router.get("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def get_ingredient(ingredient_id: int, db: Session = Depends(get_db)):
    """Fetch a single ingredient by ID."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient


@router.delete("/ingredients/{ingredient_id}", response_model=DeleteResponse)
async def delete_ingredient(
    request: Request, ingredient_id: int, db: Session = Depends(get_db)
) -> DeleteResponse:
    """Delete a global ingredient."""
    req_id = request.state.req_id
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    task_name = ingredient.task_name
    db.delete(ingredient)
    db.commit()

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
async def get_ingredients_by_recipe_name(recipe_name: str, db: Session = Depends(get_db)):
    """List ingredients for a recipe name, ordered by step_order."""
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .filter(Recipe.name == recipe_name)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")

    return [ri.ingredient for ri in recipe.recipe_ingredients if ri.ingredient is not None]


@router.get("/ingredients/by-recipe/{recipe_id}", response_model=List[IngredientResponse])
async def get_ingredients_by_recipe_id(recipe_id: int, db: Session = Depends(get_db)):
    """List ingredients for a recipe ID, ordered by step_order."""
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .filter(Recipe.id == recipe_id)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return [ri.ingredient for ri in recipe.recipe_ingredients if ri.ingredient is not None]


@router.patch("/ingredients/{ingredient_id}", response_model=IngredientResponse)
@router.put("/ingredients/{ingredient_id}", response_model=IngredientResponse)
async def update_ingredient(
    ingredient_id: int, payload: IngredientUpdate, db: Session = Depends(get_db)
) -> IngredientResponse:
    """Update a global ingredient."""
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ingredient, key, value)

    ingredient.updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()
    db.refresh(ingredient)

    return ingredient

#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for recipe and ingredient management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from api.core.database import get_db
from api.models.models import Recipe, Ingredient
from api.schemas.schemas import (
    RecipeCreate, RecipeResponse, RecipeDetailResponse,
    IngredientResponse
)

router = APIRouter()

# --- Recipe Endpoints ---

@router.post("/recipes/")
async def create_recipe(recipe: RecipeCreate, db: Session = Depends(get_db)):
    """Create a new recipe with ingredients."""
    existing = db.query(Recipe).filter(Recipe.name == recipe.name).first()
    if existing:
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
            on_failure=ingredient_data.on_failure
        )
        db.add(db_ingredient)

    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.get("/recipes/", response_model=List[RecipeDetailResponse])
async def list_recipes(
    name: Optional[str] = None,
    enabled: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """List recipes with optional filtering and nested ingredients."""
    query = db.query(Recipe).options(joinedload(Recipe.ingredients))

    if name is not None:
        query = query.filter(Recipe.name == name)
    if enabled is not None:
        query = query.filter(Recipe.enabled == enabled)

    return query.all()

@router.get("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Get a recipe with all its ingredients."""
    recipe = db.query(Recipe).options(joinedload(Recipe.ingredients)).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    return recipe

@router.get("/recipes/by-name/{recipe_name}", response_model=RecipeDetailResponse)
async def get_recipe_by_name(recipe_name: str, db: Session = Depends(get_db)):
    """Get a recipe by name (matches alert.group_name)."""
    recipe = db.query(Recipe).options(joinedload(Recipe.ingredients)).filter(Recipe.name == recipe_name).first()
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")
    
    return recipe

@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Delete a recipe and all its ingredients."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    db.delete(recipe)
    db.commit()
    return {"message": f"Recipe '{recipe.name}' deleted"}

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

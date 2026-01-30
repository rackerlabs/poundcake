#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API endpoints for recipe and ingredient management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from api.core.database import get_db
from api.models.models import Recipe, Ingredient

router = APIRouter()


class IngredientCreate(BaseModel):
    task_id: str
    task_name: str
    task_order: int
    is_blocking: bool = True
    st2_action: str
    parameters: Optional[dict] = None
    expected_time_to_completion: int
    timeout: int = 300
    retry_count: int = 0
    retry_delay: int = 5
    on_failure: str = "stop"


class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    ingredients: List[IngredientCreate]


@router.post("/api/recipes/")
async def create_recipe(recipe: RecipeCreate, db: Session = Depends(get_db)):
    """Create a new recipe with ingredients."""
    existing = db.query(Recipe).filter(Recipe.name == recipe.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Recipe '{recipe.name}' already exists")
    
    db_recipe = Recipe(name=recipe.name, description=recipe.description, enabled=recipe.enabled)
    db.add(db_recipe)
    db.flush()
    
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


@router.get("/api/recipes/")
async def list_recipes(enabled: Optional[bool] = None, db: Session = Depends(get_db)):
    """List all recipes."""
    query = db.query(Recipe)
    if enabled is not None:
        query = query.filter(Recipe.enabled == enabled)
    return query.all()


@router.get("/api/recipes/{recipe_id}")
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Get a recipe with all its ingredients."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    ingredients = db.query(Ingredient).filter(Ingredient.recipe_id == recipe_id).order_by(Ingredient.task_order).all()
    
    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "enabled": recipe.enabled,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "ingredients": ingredients
    }


@router.get("/api/recipes/by-name/{recipe_name}")
async def get_recipe_by_name(recipe_name: str, db: Session = Depends(get_db)):
    """Get a recipe by name (matches alert.group_name)."""
    recipe = db.query(Recipe).filter(Recipe.name == recipe_name).first()
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_name}' not found")
    
    ingredients = db.query(Ingredient).filter(Ingredient.recipe_id == recipe.id).order_by(Ingredient.task_order).all()
    
    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "enabled": recipe.enabled,
        "ingredients": ingredients
    }


@router.delete("/api/recipes/{recipe_id}")
async def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Delete a recipe and all its ingredients."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    db.delete(recipe)
    db.commit()
    return {"message": f"Recipe '{recipe.name}' deleted"}

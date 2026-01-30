# ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
# ╔════════════════════════════════════════════════════════════════╗
# ____                        _  ____      _         
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____ 
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# ╚════════════════════════════════════════════════════════════════╝
#
"""Recipe management API routes."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from api.core.database import get_db
from api.core.logging import get_logger
from api.models.models import Recipe

logger = get_logger(__name__)
router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# Pydantic models for request/response
class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    task_list: Optional[str] = None
    st2_workflow_ref: str
    time_to_complete: Optional[datetime] = None
    time_to_clear: Optional[datetime] = None


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    task_list: Optional[str] = None
    st2_workflow_ref: Optional[str] = None
    time_to_complete: Optional[datetime] = None
    time_to_clear: Optional[datetime] = None


class RecipeResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    task_list: Optional[str]
    st2_workflow_ref: str
    time_to_complete: Optional[datetime]
    time_to_clear: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/", response_model=RecipeResponse, status_code=201)
def create_recipe(recipe_data: RecipeCreate, db: Session = Depends(get_db)) -> Recipe:
    """Create a new recipe.

    Example:
    ```json
    {
        "name": "HostDownAlert",
        "description": "Recipe for handling host down alerts",
        "task_list": "uuid1,uuid2,uuid3",
        "st2_workflow_ref": "remediation.host_down_workflow",
        "time_to_complete": "2024-01-23T16:00:00Z",
        "time_to_clear": "2024-01-23T18:00:00Z"
    }
    ```
    """
    # Check if recipe with same name already exists
    existing = db.query(Recipe).filter(Recipe.name == recipe_data.name).first()
    if existing:
        raise HTTPException(
            status_code=400, detail=f"Recipe with name '{recipe_data.name}' already exists"
        )

    # Create new recipe
    recipe = Recipe(
        name=recipe_data.name,
        description=recipe_data.description,
        task_list=recipe_data.task_list,
        st2_workflow_ref=recipe_data.st2_workflow_ref,
        time_to_complete=recipe_data.time_to_complete,
        time_to_clear=recipe_data.time_to_clear,
    )

    db.add(recipe)
    db.commit()
    db.refresh(recipe)

    logger.info(f"Created recipe: {recipe.name}")
    return recipe


@router.get("/", response_model=List[RecipeResponse])
def list_recipes(
    name: Optional[str] = Query(None, description="Filter by recipe name"),
    limit: int = Query(100, le=1000, description="Maximum number of recipes to return"),
    offset: int = Query(0, ge=0, description="Number of recipes to skip"),
    db: Session = Depends(get_db),
) -> List[Recipe]:
    """List all recipes with optional filtering by name."""
    query = db.query(Recipe)
    
    # Filter by name if provided
    if name:
        query = query.filter(Recipe.name == name)
    
    recipes = query.order_by(desc(Recipe.created_at)).offset(offset).limit(limit).all()
    return recipes


@router.get("/{recipe_id}", response_model=RecipeResponse)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)) -> Recipe:
    """Get a specific recipe by ID."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return recipe


@router.get("/name/{recipe_name}", response_model=RecipeResponse)
def get_recipe_by_name(recipe_name: str, db: Session = Depends(get_db)) -> Recipe:
    """Get a specific recipe by name."""
    recipe = db.query(Recipe).filter(Recipe.name == recipe_name).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return recipe


@router.put("/{recipe_id}", response_model=RecipeResponse)
def update_recipe(
    recipe_id: int, recipe_data: RecipeUpdate, db: Session = Depends(get_db)
) -> Recipe:
    """Update an existing recipe."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Update fields if provided
    if recipe_data.name is not None:
        # Check if new name conflicts with existing recipe
        existing = (
            db.query(Recipe).filter(Recipe.name == recipe_data.name, Recipe.id != recipe_id).first()
        )
        if existing:
            raise HTTPException(
                status_code=400, detail=f"Recipe with name '{recipe_data.name}' already exists"
            )
        recipe.name = recipe_data.name

    if recipe_data.description is not None:
        recipe.description = recipe_data.description

    if recipe_data.task_list is not None:
        recipe.task_list = recipe_data.task_list

    if recipe_data.st2_workflow_ref is not None:
        recipe.st2_workflow_ref = recipe_data.st2_workflow_ref

    if recipe_data.time_to_complete is not None:
        recipe.time_to_complete = recipe_data.time_to_complete

    if recipe_data.time_to_clear is not None:
        recipe.time_to_clear = recipe_data.time_to_clear

    db.commit()
    db.refresh(recipe)

    logger.info(f"Updated recipe: {recipe.name}")
    return recipe


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Delete a recipe."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    logger.info(f"Deleting recipe: {recipe.name}")
    db.delete(recipe)
    db.commit()

    return None

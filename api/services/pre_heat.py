#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pre-heat service - creates ovens from alert group_name matching recipe."""

from sqlalchemy.orm import Session
from api.models.models import Alert, Recipe, Ingredient, Oven
from api.core.logging import get_logger

logger = get_logger(__name__)


def pre_heat(alert: Alert, db: Session) -> dict:
    """
    Pre-heat: Match alert.group_name to recipe and create ovens for all ingredients.
    """
    
    logger.info(f"pre_heat: Starting pre-heat for alert",
                extra={"alert_id": alert.id, "group_name": alert.group_name, 
                       "fingerprint": alert.fingerprint})
    
    recipe = db.query(Recipe).filter(
        Recipe.name == alert.group_name,
        Recipe.enabled == True
    ).first()
    
    if not recipe:
        logger.warning(f"pre_heat: No recipe found",
                      extra={"group_name": alert.group_name, "alert_id": alert.id})
        return {
            "recipe_found": False,
            "ovens_created": 0,
            "message": f"No recipe matches group_name '{alert.group_name}'"
        }
    
    logger.info(f"pre_heat: Found recipe",
                extra={"recipe_id": recipe.id, "recipe_name": recipe.name})
    
    ingredients = db.query(Ingredient)\
        .filter(Ingredient.recipe_id == recipe.id)\
        .order_by(Ingredient.task_order)\
        .all()
    
    if not ingredients:
        logger.warning(f"pre_heat: Recipe has no ingredients",
                      extra={"recipe_id": recipe.id, "recipe_name": recipe.name})
        return {
            "recipe_found": True,
            "recipe_name": recipe.name,
            "ovens_created": 0,
            "message": "Recipe has no ingredients"
        }
    
    logger.info(f"pre_heat: Creating ovens for ingredients",
                extra={"ingredient_count": len(ingredients)})
    
    ovens_created = []
    
    for ingredient in ingredients:
        oven = Oven(
            req_id=alert.req_id,
            alert_id=alert.id,
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            processing_status="new",
            task_order=ingredient.task_order,
            is_blocking=ingredient.is_blocking,
            expected_duration=ingredient.expected_time_to_completion
        )
        db.add(oven)
        ovens_created.append({
            "task_order": ingredient.task_order,
            "task_name": ingredient.task_name,
            "is_blocking": ingredient.is_blocking
        })
        
        logger.info(f"pre_heat: Created oven",
                   extra={"task_order": ingredient.task_order, 
                          "task_name": ingredient.task_name,
                          "is_blocking": ingredient.is_blocking})
    
    alert.processing_status = "processing"
    db.commit()
    
    logger.info(f"pre_heat: Complete",
                extra={"alert_id": alert.id, "recipe_name": recipe.name,
                       "ovens_created": len(ovens_created)})
    
    return {
        "recipe_found": True,
        "recipe_name": recipe.name,
        "recipe_id": recipe.id,
        "ovens_created": len(ovens_created),
        "ovens": ovens_created
    }

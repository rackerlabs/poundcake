from api.models.models import Ingredient, Recipe
from api.schemas.schemas import IngredientCreate, RecipeCreate, RecipeIngredientCreate


def test_model_defaults_and_constraints_align_with_alembic_contract():
    assert Ingredient.__table__.c.execution_engine.default.arg == "undefined"
    assert Ingredient.__table__.c.ingredient_kind.default.arg == "utility"
    assert Ingredient.__table__.c.execution_target.unique is True
    assert Recipe.__table__.c.deleted.nullable is False
    assert Ingredient.__table__.c.deleted.nullable is False


def test_schema_defaults_execution_engine_are_undefined():
    ingredient = IngredientCreate(
        execution_target="core.local",
        task_key_template="core.local",
        expected_duration_sec=30,
    )
    assert ingredient.execution_engine == "undefined"
    assert ingredient.ingredient_kind == "utility"

    recipe = RecipeCreate(
        name="recipe-default-source-type",
        recipe_ingredients=[
            RecipeIngredientCreate(
                ingredient_id=1,
                step_order=1,
            )
        ],
    )
    assert recipe.enabled is True
    assert recipe.recipe_ingredients[0].run_phase == "both"

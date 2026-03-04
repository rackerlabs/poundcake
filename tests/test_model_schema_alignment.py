from api.models.models import Ingredient, Recipe
from api.schemas.schemas import IngredientCreate, RecipeCreate, RecipeIngredientCreate
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON


def test_model_defaults_and_constraints_align_with_alembic_contract():
    assert Ingredient.__table__.c.execution_engine.default.arg == "undefined"
    assert Ingredient.__table__.c.execution_purpose.default.arg == "utility"
    assert Ingredient.__table__.c.execution_target.unique is None
    assert isinstance(Ingredient.__table__.c.execution_payload.type, MYSQL_JSON)
    assert any(
        getattr(constraint, "name", "") == "ux_ingredients_engine_target"
        for constraint in Ingredient.__table__.constraints
    )
    assert Recipe.__table__.c.deleted.nullable is False
    assert Ingredient.__table__.c.deleted.nullable is False


def test_schema_defaults_execution_engine_are_undefined():
    ingredient = IngredientCreate(
        execution_target="core.local",
        task_key_template="core.local",
        expected_duration_sec=30,
    )
    assert ingredient.execution_engine == "undefined"
    assert ingredient.execution_purpose == "utility"

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

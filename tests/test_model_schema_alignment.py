from api.models.models import Ingredient, Recipe, RecipeIngredient
from api.schemas.schemas import IngredientCreate, RecipeCreate, RecipeIngredientCreate
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON


def test_model_defaults_and_constraints_align_with_alembic_contract():
    assert Ingredient.__table__.c.execution_engine.default.arg == "undefined"
    assert Ingredient.__table__.c.execution_purpose.default.arg == "utility"
    assert Ingredient.__table__.c.is_default.default.arg is False
    assert Ingredient.__table__.c.is_active.default.arg is True
    assert Ingredient.__table__.c.execution_target.unique is None
    assert isinstance(Ingredient.__table__.c.execution_payload.type, MYSQL_JSON)
    assert isinstance(RecipeIngredient.__table__.c.execution_payload_override.type, MYSQL_JSON)
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
    assert ingredient.is_default is False
    assert ingredient.is_active is True

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
    assert recipe.recipe_ingredients[0].execution_payload_override is None

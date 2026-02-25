from api.models.models import Ingredient, Recipe
from api.schemas.schemas import IngredientCreate, RecipeCreate, RecipeIngredientCreate


def test_model_defaults_and_constraints_align_with_alembic_contract():
    assert Recipe.__table__.c.source_type.default.arg == "undefined"
    assert Ingredient.__table__.c.source_type.default.arg == "undefined"
    assert Ingredient.__table__.c.task_id.unique is True
    assert Recipe.__table__.c.deleted.nullable is False
    assert Ingredient.__table__.c.deleted.nullable is False


def test_schema_defaults_source_type_are_undefined():
    ingredient = IngredientCreate(
        task_id="core.local",
        task_name="core.local",
        expected_duration_sec=30,
    )
    assert ingredient.source_type == "undefined"

    recipe = RecipeCreate(
        name="recipe-default-source-type",
        recipe_ingredients=[
            RecipeIngredientCreate(
                ingredient_id=1,
                step_order=1,
            )
        ],
    )
    assert recipe.source_type == "undefined"

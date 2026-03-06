from types import SimpleNamespace

from api.services.dish_planner import seed_dish_ingredients_for_phase


def _recipe_ingredient(
    *,
    ri_id: int,
    run_phase: str,
    engine: str,
    purpose: str,
    target: str = "core.local",
    task_key_template: str = "task",
):
    ingredient = SimpleNamespace(
        execution_engine=engine,
        execution_purpose=purpose,
        execution_target=target,
        task_key_template=task_key_template,
        execution_payload=None,
        execution_parameters={},
    )
    return SimpleNamespace(
        id=ri_id,
        step_order=ri_id,
        run_phase=run_phase,
        execution_parameters_override=None,
        ingredient=ingredient,
    )


def test_seed_dish_ingredients_for_phase__resolving_excludes_stackstorm_even_when_both():
    recipe = SimpleNamespace(
        recipe_ingredients=[
            _recipe_ingredient(
                ri_id=1,
                run_phase="both",
                engine="stackstorm",
                purpose="remediation",
                task_key_template="local",
            )
        ]
    )

    rows = seed_dish_ingredients_for_phase(dish_id=101, recipe=recipe, phase="resolving")

    assert rows == []


def test_seed_dish_ingredients_for_phase__resolving_keeps_only_bakery_comms():
    recipe = SimpleNamespace(
        recipe_ingredients=[
            _recipe_ingredient(
                ri_id=1,
                run_phase="both",
                engine="bakery",
                purpose="comms",
                target="core",
                task_key_template="core",
            ),
            _recipe_ingredient(
                ri_id=2,
                run_phase="both",
                engine="bakery",
                purpose="utility",
                target="core",
                task_key_template="core_util",
            ),
        ]
    )

    rows = seed_dish_ingredients_for_phase(dish_id=101, recipe=recipe, phase="resolving")

    assert len(rows) == 1
    assert rows[0].recipe_ingredient_id == 1
    assert rows[0].execution_engine == "bakery"

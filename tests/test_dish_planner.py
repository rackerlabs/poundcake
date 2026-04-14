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
        execution_payload={"template": {"name": task_key_template}},
        execution_parameters={"base": "value"},
        expected_duration_sec=30,
        timeout_duration_sec=120,
        retry_count=1,
        retry_delay=5,
        on_failure="stop",
    )
    return SimpleNamespace(
        id=ri_id,
        step_order=ri_id,
        run_phase=run_phase,
        execution_payload_override=None,
        execution_parameters_override=None,
        expected_duration_sec_override=None,
        timeout_duration_sec_override=None,
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


def test_seed_dish_ingredients_for_phase__resolves_override_fields():
    recipe_step = _recipe_ingredient(
        ri_id=1,
        run_phase="firing",
        engine="bakery",
        purpose="comms",
        target="core",
        task_key_template="core",
    )
    recipe_step.execution_payload_override = {"extra": "payload"}
    recipe_step.execution_parameters_override = {"override": "value"}
    recipe_step.expected_duration_sec_override = 45
    recipe_step.timeout_duration_sec_override = 180
    recipe = SimpleNamespace(recipe_ingredients=[recipe_step])

    rows = seed_dish_ingredients_for_phase(dish_id=101, recipe=recipe, phase="firing")

    assert len(rows) == 1
    assert rows[0].execution_payload == {"name": "core", "extra": "payload"}
    assert rows[0].execution_parameters == {"base": "value", "override": "value"}
    assert rows[0].expected_duration_sec == 45
    assert rows[0].timeout_duration_sec == 180


def test_seed_dish_ingredients_for_phase__unwraps_bakery_template_context():
    recipe_step = _recipe_ingredient(
        ri_id=1,
        run_phase="firing",
        engine="bakery",
        purpose="comms",
        target="core",
        task_key_template="core",
    )
    recipe_step.ingredient.execution_payload = {
        "template": {
            "title": "Alert requires attention",
            "context": {"source": "poundcake"},
        }
    }
    recipe_step.execution_payload_override = {
        "description": "Disk is filling up",
        "context": {"route": "rackspace"},
    }
    recipe = SimpleNamespace(recipe_ingredients=[recipe_step])

    rows = seed_dish_ingredients_for_phase(dish_id=101, recipe=recipe, phase="firing")

    assert len(rows) == 1
    assert rows[0].execution_payload == {
        "title": "Alert requires attention",
        "description": "Disk is filling up",
        "context": {
            "source": "poundcake",
            "route": "rackspace",
        },
    }

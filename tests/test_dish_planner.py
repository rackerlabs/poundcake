from types import SimpleNamespace

from api.services.dish_planner import build_step_execution_payload, seed_dish_ingredients_for_phase


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


def test_build_step_execution_payload_resolves_template_and_runtime_context():
    order = SimpleNamespace(
        id=1,
        req_id="REQ-1",
        processing_status="resolving",
        alert_status="resolved",
        counter=1,
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="disk-alert",
        severity="warning",
        fingerprint="fp-1",
        instance="host-1",
        starts_at=None,
        ends_at=None,
        labels={},
        annotations={},
        raw_data={},
        remediation_outcome="pending",
        dishes=[],
    )
    ingredient = SimpleNamespace(
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="core",
        destination_target="ops",
        task_key_template="notify",
        execution_payload={
            "template": {
                "comment": "base",
                "context": {
                    "labels": {"team": "storage"},
                    "destination_target": "template-destination",
                },
            },
            "context": {"labels": {"service": "disk"}},
        },
        execution_parameters={"operation": "ticket_comment"},
    )
    ri = SimpleNamespace(
        ingredient=ingredient,
        execution_parameters_override={"context": {"labels": {"cluster": "prod"}}},
    )

    payload = build_step_execution_payload(ri=ri, order=order)

    assert payload["comment"] == "base"
    assert "template" not in payload
    assert payload["context"]["provider_type"] == "core"
    assert payload["context"]["destination_target"] == "ops"
    assert payload["context"]["labels"] == {"team": "storage", "service": "disk"}
    assert "_canonical" in payload["context"]

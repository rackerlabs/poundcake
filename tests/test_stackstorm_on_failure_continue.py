"""Tests for workflow transitions when ingredient on_failure is continue."""

from __future__ import annotations

import yaml

from api.services.stackstorm_service import generate_orquesta_yaml


def _recipe_dict(on_failure: str) -> dict:
    return {
        "name": "HostDownContinue",
        "description": "test",
        "recipe_ingredients": [
            {
                "step_order": 1,
                "depth": 0,
                "execution_parameters_override": {"cmd": "ping -c 1 no-such-host.invalid"},
                "ingredient": {
                    "task_key_template": "check_host",
                    "execution_target": "core.local",
                    "retry_count": 0,
                    "retry_delay": 0,
                    "is_blocking": True,
                    "on_failure": on_failure,
                },
            },
            {
                "step_order": 2,
                "depth": 0,
                "execution_parameters_override": {"cmd": "echo ok"},
                "ingredient": {
                    "task_key_template": "follow_up",
                    "execution_target": "core.local",
                    "retry_count": 0,
                    "retry_delay": 0,
                    "is_blocking": True,
                    "on_failure": "stop",
                },
            },
        ],
    }


def test_generate_orquesta_yaml_adds_failed_transition_for_continue() -> None:
    workflow = yaml.safe_load(generate_orquesta_yaml(_recipe_dict("continue")))

    step1 = workflow["tasks"]["step_1_check_host"]
    next_rules = step1.get("next", [])

    assert {rule.get("when") for rule in next_rules} == {"<% succeeded() %>", "<% failed() %>"}


def test_generate_orquesta_yaml_does_not_add_failed_transition_for_stop() -> None:
    workflow = yaml.safe_load(generate_orquesta_yaml(_recipe_dict("stop")))

    step1 = workflow["tasks"]["step_1_check_host"]
    next_rules = step1.get("next", [])

    assert {rule.get("when") for rule in next_rules} == {"<% succeeded() %>"}

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import yaml

_MODULE_PATH = Path(__file__).resolve().parents[1] / "api" / "services" / "stackstorm_service.py"
_SPEC = spec_from_file_location("stackstorm_service_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
generate_orquesta_yaml = _MODULE.generate_orquesta_yaml


def _recipe_with_steps(steps):
    recipe_ingredients = []
    for step in steps:
        recipe_ingredients.append(
            {
                "step_order": step["step_order"],
                "depth": step.get("depth", 0),
                "input_parameters": step.get("input_parameters", {}),
                "ingredient": {
                    "task_id": step.get("task_id", "core.local"),
                    "task_name": step["task_name"],
                    "is_blocking": step["is_blocking"],
                    "retry_count": 0,
                    "retry_delay": 0,
                },
            }
        )
    return {
        "name": "test-workflow",
        "description": "test",
        "recipe_ingredients": recipe_ingredients,
    }


def test_mixed_blocking_non_blocking_builds_fork_and_join():
    recipe = _recipe_with_steps(
        [
            {"step_order": 1, "task_name": "task1", "is_blocking": True},
            {"step_order": 2, "task_name": "task2", "is_blocking": False},
            {"step_order": 3, "task_name": "task3", "is_blocking": False},
            {"step_order": 4, "task_name": "task4", "is_blocking": False},
            {"step_order": 5, "task_name": "task5", "is_blocking": True},
        ]
    )

    workflow = yaml.safe_load(generate_orquesta_yaml(recipe))
    tasks = workflow["tasks"]

    task1_next = tasks["step_1_task1"]["next"]
    assert task1_next == [
        {
            "when": "<% succeeded() %>",
            "do": ["step_2_task2", "step_3_task3", "step_4_task4"],
        }
    ]

    for step_name in ["step_2_task2", "step_3_task3", "step_4_task4"]:
        assert tasks[step_name]["next"] == [
            {
                "when": "<% succeeded() %>",
                "do": "step_5_task5",
            }
        ]

    assert tasks["step_5_task5"]["join"] == "all"
    assert workflow["output"] == [{"result": "<% task(step_5_task5).result %>"}]


def test_non_blocking_depth_transition_uses_parallel_fork():
    recipe = _recipe_with_steps(
        [
            {"step_order": 1, "depth": 0, "task_name": "task1", "is_blocking": False},
            {"step_order": 2, "depth": 1, "task_name": "task2", "is_blocking": False},
            {"step_order": 3, "depth": 1, "task_name": "task3", "is_blocking": False},
        ]
    )

    workflow = yaml.safe_load(generate_orquesta_yaml(recipe))
    task1_next = workflow["tasks"]["step_1_task1"]["next"]
    assert task1_next == [
        {
            "when": "<% succeeded() %>",
            "do": ["step_2_task2", "step_3_task3"],
        }
    ]


def test_all_blocking_tasks_chain_sequentially():
    recipe = _recipe_with_steps(
        [
            {"step_order": 1, "task_name": "task1", "is_blocking": True},
            {"step_order": 2, "task_name": "task2", "is_blocking": True},
            {"step_order": 3, "task_name": "task3", "is_blocking": True},
        ]
    )

    workflow = yaml.safe_load(generate_orquesta_yaml(recipe))
    tasks = workflow["tasks"]

    assert tasks["step_1_task1"]["next"] == [{"when": "<% succeeded() %>", "do": "step_2_task2"}]
    assert tasks["step_2_task2"]["next"] == [{"when": "<% succeeded() %>", "do": "step_3_task3"}]
    assert "next" not in tasks["step_3_task3"]
    assert "join" not in tasks["step_3_task3"]


def test_all_non_blocking_tasks_without_depth_start_in_parallel():
    recipe = _recipe_with_steps(
        [
            {"step_order": 1, "task_name": "task1", "is_blocking": False},
            {"step_order": 2, "task_name": "task2", "is_blocking": False},
            {"step_order": 3, "task_name": "task3", "is_blocking": False},
        ]
    )

    workflow = yaml.safe_load(generate_orquesta_yaml(recipe))
    tasks = workflow["tasks"]

    # Tasks with no inbound edges are all starting tasks in Orquesta.
    assert "next" not in tasks["step_1_task1"]
    assert "next" not in tasks["step_2_task2"]
    assert "next" not in tasks["step_3_task3"]
    assert all("join" not in tasks[t] for t in tasks)


def test_non_blocking_group_to_blocking_to_non_blocking_group():
    recipe = _recipe_with_steps(
        [
            {"step_order": 1, "task_name": "task1", "is_blocking": False},
            {"step_order": 2, "task_name": "task2", "is_blocking": False},
            {"step_order": 3, "task_name": "task3", "is_blocking": True},
            {"step_order": 4, "task_name": "task4", "is_blocking": False},
            {"step_order": 5, "task_name": "task5", "is_blocking": False},
        ]
    )

    workflow = yaml.safe_load(generate_orquesta_yaml(recipe))
    tasks = workflow["tasks"]

    assert tasks["step_3_task3"]["join"] == "all"
    assert tasks["step_1_task1"]["next"] == [{"when": "<% succeeded() %>", "do": "step_3_task3"}]
    assert tasks["step_2_task2"]["next"] == [{"when": "<% succeeded() %>", "do": "step_3_task3"}]
    assert tasks["step_3_task3"]["next"] == [
        {"when": "<% succeeded() %>", "do": ["step_4_task4", "step_5_task5"]}
    ]

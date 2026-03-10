from __future__ import annotations

from kitchen.execution_segments import (
    next_pending_execution_segment,
    sort_ingredients_for_execution,
)


def test_sort_ingredients_for_execution_uses_recipe_step_order():
    dish = {
        "recipe": {
            "recipe_ingredients": [
                {"id": 20, "step_order": 2},
                {"id": 10, "step_order": 1},
            ]
        }
    }
    ingredients = [
        {"recipe_ingredient_id": 20, "task_key": "step_2_b", "execution_status": "pending"},
        {"recipe_ingredient_id": 10, "task_key": "step_1_a", "execution_status": "pending"},
    ]

    ordered = sort_ingredients_for_execution(dish, ingredients)

    assert [item["recipe_ingredient_id"] for item in ordered] == [10, 20]


def test_next_pending_execution_segment_returns_contiguous_engine_slice():
    dish = {
        "recipe": {
            "recipe_ingredients": [
                {"id": 1, "step_order": 1},
                {"id": 2, "step_order": 2},
                {"id": 3, "step_order": 3},
                {"id": 4, "step_order": 4},
            ]
        }
    }
    ingredients = [
        {
            "recipe_ingredient_id": 1,
            "task_key": "step_1_notify",
            "execution_engine": "bakery",
            "execution_status": "succeeded",
        },
        {
            "recipe_ingredient_id": 2,
            "task_key": "step_2_remediate_a",
            "execution_engine": "stackstorm",
            "execution_status": "pending",
        },
        {
            "recipe_ingredient_id": 3,
            "task_key": "step_3_remediate_b",
            "execution_engine": "stackstorm",
            "execution_status": "pending",
        },
        {
            "recipe_ingredient_id": 4,
            "task_key": "step_4_update",
            "execution_engine": "bakery",
            "execution_status": "pending",
        },
    ]

    segment = next_pending_execution_segment(dish, ingredients)

    assert segment is not None
    engine, rows = segment
    assert engine == "stackstorm"
    assert [item["recipe_ingredient_id"] for item in rows] == [2, 3]

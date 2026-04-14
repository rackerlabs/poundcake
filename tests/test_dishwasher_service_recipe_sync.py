from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import RecipeIngredient
from api.services.dishwasher_service import sync_recipe_ingredients_from_yaml


class _ScalarResult:
    def __init__(self, all_=None):
        self._all = all_ or []

    def scalars(self):
        return self

    def all(self):
        return self._all


@pytest.mark.asyncio
async def test_sync_recipe_ingredients_from_yaml_detaches_historical_dish_refs():
    recipe = SimpleNamespace(id=12)
    ingredient = SimpleNamespace(id=41, execution_target="core.test")
    dish_row = SimpleNamespace(
        id=91,
        dish_id=3,
        recipe_ingredient_id=81,
        task_key="notify",
        updated_at=None,
    )
    added: list[object] = []

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[ingredient]),  # existing ingredients
            _ScalarResult(all_=[81]),  # existing recipe_ingredient ids
            _ScalarResult(all_=[dish_row]),  # impacted dish_ingredients
            _ScalarResult(all_=[(91, 3, 81, "notify")]),  # occupancy query
            _ScalarResult(),  # delete recipe_ingredients
        ]
    )
    db.add = Mock(side_effect=added.append)
    db.flush = AsyncMock()

    ok = await sync_recipe_ingredients_from_yaml(
        db,
        recipe,
        {"tasks": {"notify": {"action": "core.test"}}},
        strict=False,
    )

    assert ok is True
    assert dish_row.recipe_ingredient_id is None
    assert dish_row.task_key == "notify"
    db.flush.assert_awaited_once()
    statements = [
        call.args[0] for call in db.execute.call_args_list if hasattr(call.args[0], "table")
    ]
    assert [stmt.table.name for stmt in statements] == ["recipe_ingredients"]
    steps = [row for row in added if isinstance(row, RecipeIngredient)]
    assert len(steps) == 1
    assert steps[0].ingredient_id == 41

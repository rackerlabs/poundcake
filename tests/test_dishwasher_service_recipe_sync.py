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
    added: list[object] = []

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[ingredient]),  # existing ingredients
            _ScalarResult(),  # detach dish_ingredients
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
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert [stmt.table.name for stmt in statements[-2:]] == [
        "dish_ingredients",
        "recipe_ingredients",
    ]
    steps = [row for row in added if isinstance(row, RecipeIngredient)]
    assert len(steps) == 1
    assert steps[0].ingredient_id == 41

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.recipe_ingredient_cleanup import detach_recipe_ingredient_ids_safely


class _ScalarResult:
    def __init__(self, all_=None):
        self._all = all_ or []

    def scalars(self):
        return self

    def all(self):
        return self._all


@pytest.mark.asyncio
async def test_detach_recipe_ingredient_ids_safely_preserves_one_logical_task_key():
    now = datetime.now(timezone.utc)
    primary = SimpleNamespace(
        id=101,
        dish_id=7,
        recipe_ingredient_id=41,
        task_key="step_2010_pcmcomms_fallback",
        updated_at=now,
    )
    duplicate = SimpleNamespace(
        id=102,
        dish_id=7,
        recipe_ingredient_id=42,
        task_key="step_2010_pcmcomms_fallback",
        updated_at=now,
    )
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[primary, duplicate]),
            _ScalarResult(
                all_=[
                    (101, 7, 41, "step_2010_pcmcomms_fallback"),
                    (102, 7, 42, "step_2010_pcmcomms_fallback"),
                ]
            ),
        ]
    )
    db.flush = AsyncMock()

    await detach_recipe_ingredient_ids_safely(db, recipe_ingredient_ids=[41, 42])

    assert primary.recipe_ingredient_id is None
    assert duplicate.recipe_ingredient_id is None
    assert {primary.task_key, duplicate.task_key} == {
        "step_2010_pcmcomms_fallback",
        "step_2010_pcmcomms_fallback::detached::102",
    }
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_detach_recipe_ingredient_ids_safely_avoids_existing_detached_collision():
    row = SimpleNamespace(
        id=111,
        dish_id=8,
        recipe_ingredient_id=51,
        task_key="step_2010_pcmcomms_fallback",
        updated_at=datetime.now(timezone.utc),
    )
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[row]),
            _ScalarResult(
                all_=[
                    (111, 8, 51, "step_2010_pcmcomms_fallback"),
                    (211, 8, None, "step_2010_pcmcomms_fallback"),
                ]
            ),
        ]
    )
    db.flush = AsyncMock()

    await detach_recipe_ingredient_ids_safely(db, recipe_ingredient_ids=[51])

    assert row.recipe_ingredient_id is None
    assert row.task_key == "step_2010_pcmcomms_fallback::detached::111"
    db.flush.assert_awaited_once()

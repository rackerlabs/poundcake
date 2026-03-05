from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from api.services.fallback_recipe import ensure_fallback_recipe


class _ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first

    def unique(self):
        return self


class _NestedContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_recovers_from_duplicate_core_ingredient_insert():
    existing_ingredient = SimpleNamespace(
        id=5,
        execution_engine="bakery",
        execution_target="core",
        is_default=False,
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )
    existing_step = SimpleNamespace(
        ingredient_id=5,
        step_order=1,
        run_phase="resolving",
        on_success="continue",
    )
    existing_recipe = SimpleNamespace(
        id=10,
        name="fallback-recipe",
        enabled=True,
        deleted=False,
        deleted_at=None,
        updated_at=None,
        recipe_ingredients=[existing_step],
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(first=None),  # first ingredient lookup
            _ScalarResult(first=existing_ingredient),  # retry ingredient lookup after conflict
            _ScalarResult(first=existing_recipe),  # recipe lookup
        ]
    )
    db.add = Mock()
    db.begin_nested = Mock(return_value=_NestedContext())
    db.flush = AsyncMock(side_effect=[IntegrityError("INSERT", {}, Exception("dup"))])

    with patch(
        "api.services.fallback_recipe.get_settings",
        return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
    ):
        recipe = await ensure_fallback_recipe(db, req_id="REQ-RACE")

    assert recipe is existing_recipe
    assert existing_ingredient.is_default is True

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


class _RecipeWithoutLazyIngredients:
    def __init__(self, *, recipe_id: int, name: str):
        self.id = recipe_id
        self.name = name
        self.enabled = True
        self.deleted = False
        self.deleted_at = None
        self.updated_at = None

    @property
    def recipe_ingredients(self):
        raise AssertionError(
            "ensure_fallback_recipe should not lazy-load recipe.recipe_ingredients"
        )


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
            _ScalarResult(first=existing_step),  # existing first step lookup
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


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_uses_explicit_step_query_not_relationship_lazy_load():
    existing_ingredient = SimpleNamespace(
        id=7,
        execution_engine="bakery",
        execution_target="core",
        is_default=True,
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )
    existing_recipe = _RecipeWithoutLazyIngredients(recipe_id=22, name="fallback-recipe")
    existing_step = SimpleNamespace(
        ingredient_id=999,
        step_order=1,
        run_phase="firing",
        on_success="stop",
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(first=existing_ingredient),  # ingredient lookup
            _ScalarResult(first=existing_recipe),  # recipe lookup
            _ScalarResult(first=existing_step),  # explicit first-step lookup
        ]
    )
    db.add = Mock()
    db.begin_nested = Mock(return_value=_NestedContext())
    db.flush = AsyncMock()

    with patch(
        "api.services.fallback_recipe.get_settings",
        return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
    ):
        recipe = await ensure_fallback_recipe(db, req_id="REQ-NO-LAZY")

    assert recipe is existing_recipe
    assert existing_step.ingredient_id == existing_ingredient.id
    assert existing_step.run_phase == "resolving"
    assert existing_step.on_success == "continue"

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from api.models.models import Ingredient, RecipeIngredient
from api.services.fallback_recipe import ensure_fallback_recipe


class _ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first


class _NestedContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_recovers_from_duplicate_managed_ingredient_insert():
    existing_open = Ingredient(
        id=5,
        execution_engine="bakery",
        execution_target="rackspace_core",
        destination_target="",
        task_key_template="fallback_open",
        execution_purpose="utility",
        execution_payload={},
        execution_parameters={"operation": "open"},
        is_default=False,
        is_blocking=False,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=0,
        retry_delay=0,
        on_failure="stop",
        deleted=False,
    )
    existing_update = Ingredient(
        id=6,
        execution_engine="bakery",
        execution_target="rackspace_core",
        destination_target="",
        task_key_template="fallback_update",
        execution_purpose="utility",
        execution_payload={},
        execution_parameters={"operation": "update"},
        is_default=False,
        is_blocking=False,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=0,
        retry_delay=0,
        on_failure="stop",
        deleted=False,
    )
    recipe = Mock(
        id=10,
        name="fallback-recipe",
        enabled=True,
        description="old",
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(first=None),
            _ScalarResult(first=existing_open),
            _ScalarResult(first=existing_update),
            _ScalarResult(first=recipe),
            _ScalarResult(first=None),
        ]
    )
    db.add = Mock()
    db.begin_nested = Mock(return_value=_NestedContext())
    db.flush = AsyncMock(side_effect=[IntegrityError("INSERT", {}, Exception("dup"))])

    with patch(
        "api.services.fallback_recipe.get_settings",
        return_value=SimpleNamespace(
            catch_all_recipe_name="fallback-recipe",
            bakery_active_provider="rackspace_core",
        ),
    ):
        result = await ensure_fallback_recipe(db, req_id="REQ-RACE")

    assert result is recipe
    assert existing_open.is_default is True
    assert existing_open.execution_purpose == "comms"
    assert existing_update.is_default is True
    assert existing_update.execution_purpose == "comms"


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_builds_firing_open_and_resolving_update_steps():
    open_ingredient = Ingredient(
        id=7,
        execution_engine="bakery",
        execution_target="rackspace_core",
        destination_target="",
        task_key_template="fallback_open",
        execution_purpose="comms",
        execution_payload={},
        execution_parameters={"operation": "open"},
        is_default=True,
        is_blocking=False,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=1,
        retry_delay=5,
        on_failure="continue",
        deleted=False,
    )
    update_ingredient = Ingredient(
        id=8,
        execution_engine="bakery",
        execution_target="rackspace_core",
        destination_target="",
        task_key_template="fallback_update",
        execution_purpose="comms",
        execution_payload={},
        execution_parameters={"operation": "update"},
        is_default=True,
        is_blocking=False,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=1,
        retry_delay=5,
        on_failure="continue",
        deleted=False,
    )
    recipe = SimpleNamespace(
        id=22,
        name="fallback-recipe",
        enabled=True,
        description="old",
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )
    added: list[object] = []

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(first=open_ingredient),
            _ScalarResult(first=update_ingredient),
            _ScalarResult(first=recipe),
            _ScalarResult(first=None),
        ]
    )
    db.add = Mock(side_effect=added.append)
    db.begin_nested = Mock(return_value=_NestedContext())
    db.flush = AsyncMock()

    with patch(
        "api.services.fallback_recipe.get_settings",
        return_value=SimpleNamespace(
            catch_all_recipe_name="fallback-recipe",
            bakery_active_provider="rackspace_core",
        ),
    ):
        result = await ensure_fallback_recipe(db, req_id="REQ-FALLBACK")

    assert result is recipe
    steps = [item for item in added if isinstance(item, RecipeIngredient)]
    assert len(steps) == 2
    assert [(step.step_order, step.run_phase, step.run_condition) for step in steps] == [
        (1, "firing", "always"),
        (2, "resolving", "resolved_after_no_remediation"),
    ]

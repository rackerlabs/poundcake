from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import Recipe, RecipeIngredient
from api.services.bootstrap_recipe_catalog import (
    load_bootstrap_recipe_catalog,
    upsert_bootstrap_recipe_catalog,
)


class _ScalarResult:
    def __init__(self, first=None, all_=None):
        self._first = first
        self._all = all_ or []

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all


def test_load_bootstrap_recipe_catalog_accepts_valid_entries(tmp_path) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "node-a.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  name: node-a
  description: test
  enabled: true
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      task_key_template: rackspace_core.update
      step_order: 1
      run_phase: resolving
      on_success: continue
      parallel_group: 0
      depth: 0
      execution_parameters_override: null
""".strip(),
        encoding="utf-8",
    )
    items, errors = load_bootstrap_recipe_catalog(str(recipes_dir))
    assert errors == []
    assert len(items) == 1
    assert items[0]["name"] == "node-a"
    assert items[0]["recipe_ingredients"][0]["run_phase"] == "resolving"


def test_load_bootstrap_recipe_catalog_rejects_invalid_recipe(tmp_path) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "bad.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  description: missing name
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      run_phase: invalid
""".strip(),
        encoding="utf-8",
    )
    items, errors = load_bootstrap_recipe_catalog(str(recipes_dir))
    assert items == []
    assert len(errors) >= 2
    assert any("recipe.name is required" in err for err in errors)
    assert any(".run_phase must be one of" in err for err in errors)


@pytest.mark.asyncio
async def test_upsert_bootstrap_recipe_catalog_creates_and_updates(tmp_path) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "node-a.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  name: node-a
  description: generated
  enabled: true
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      task_key_template: rackspace_core.update
      step_order: 1
      run_phase: resolving
      on_success: continue
      parallel_group: 0
      depth: 0
      execution_parameters_override: null
""".strip(),
        encoding="utf-8",
    )
    (recipes_dir / "node-b.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  name: node-b
  description: generated
  enabled: true
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      task_key_template: rackspace_core.update
      step_order: 1
      run_phase: resolving
      on_success: continue
      parallel_group: 0
      depth: 0
      execution_parameters_override: null
""".strip(),
        encoding="utf-8",
    )

    ingredient = SimpleNamespace(
        id=41,
        execution_engine="bakery",
        execution_target="rackspace_core",
        task_key_template="rackspace_core.update",
        destination_target="",
    )
    existing_recipe = SimpleNamespace(
        id=7,
        name="node-a",
        description="Bootstrap-managed remote recipe for alert rule node-a [source-sha256:old]",
        enabled=False,
        clear_timeout_sec=None,
        recipe_ingredients=[],
        deleted=True,
        deleted_at="2026-01-01",
        updated_at=None,
    )
    db = AsyncMock()
    db.add = Mock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[ingredient]),  # ingredient map
            _ScalarResult(first=existing_recipe),  # node-a
            _ScalarResult(all_=[]),  # node-a recipe_ingredient ids
            _ScalarResult(),  # delete node-a recipe_ingredients
            _ScalarResult(first=None),  # node-b
            _ScalarResult(all_=[]),  # node-b recipe_ingredient ids
            _ScalarResult(),  # delete node-b recipe_ingredients
        ]
    )
    db.flush = AsyncMock(return_value=None)
    db.commit = AsyncMock(return_value=None)

    stats = await upsert_bootstrap_recipe_catalog(db, recipes_dir=str(recipes_dir))

    assert stats["processed"] == 2
    assert stats["created"] == 1
    assert stats["updated"] == 1
    assert stats["conflicts"] == 0
    assert stats["errors"] == 0

    assert existing_recipe.description == "generated"
    assert existing_recipe.enabled is True
    assert existing_recipe.deleted is False
    assert existing_recipe.deleted_at is None

    dml_tables = [
        stmt.table.name
        for stmt in (call.args[0] for call in db.execute.call_args_list)
        if hasattr(stmt, "table")
    ]
    assert dml_tables == [
        "recipe_ingredients",
        "recipe_ingredients",
    ]

    added_rows = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(row, Recipe) and row.name == "node-b" for row in added_rows)
    assert any(isinstance(row, RecipeIngredient) for row in added_rows)


@pytest.mark.asyncio
async def test_upsert_bootstrap_recipe_catalog_reports_missing_ingredient_ref(tmp_path) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "node-a.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  name: node-a
  enabled: true
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      task_key_template: rackspace_core.update
      step_order: 1
      run_phase: resolving
      on_success: continue
      parallel_group: 0
      depth: 0
      execution_parameters_override: null
""".strip(),
        encoding="utf-8",
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(all_=[]))
    db.commit = AsyncMock(return_value=None)
    db.add = Mock()

    stats = await upsert_bootstrap_recipe_catalog(db, recipes_dir=str(recipes_dir))
    assert stats["processed"] == 0
    assert stats["errors"] == 1
    assert "missing ingredient refs" in stats["error_messages"][0]


@pytest.mark.asyncio
async def test_upsert_bootstrap_recipe_catalog_reports_conflict_for_non_managed_recipe(
    tmp_path,
) -> None:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "node-a.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: RecipeCatalogEntry
recipe:
  name: node-a
  description: generated
  enabled: true
  recipe_ingredients:
    - execution_engine: bakery
      execution_target: rackspace_core
      task_key_template: rackspace_core.update
      step_order: 1
      run_phase: resolving
      on_success: continue
      parallel_group: 0
      depth: 0
      execution_parameters_override: null
""".strip(),
        encoding="utf-8",
    )
    ingredient = SimpleNamespace(
        id=41,
        execution_engine="bakery",
        execution_target="rackspace_core",
        task_key_template="rackspace_core.update",
        destination_target="",
    )
    existing_recipe = SimpleNamespace(
        id=7,
        name="node-a",
        description="User workflow",
        enabled=True,
        clear_timeout_sec=None,
        recipe_ingredients=[],
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )
    db = AsyncMock()
    db.add = Mock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(all_=[ingredient]),
            _ScalarResult(first=existing_recipe),
        ]
    )
    db.commit = AsyncMock(return_value=None)

    stats = await upsert_bootstrap_recipe_catalog(db, recipes_dir=str(recipes_dir))

    assert stats["processed"] == 1
    assert stats["created"] == 0
    assert stats["updated"] == 0
    assert stats["conflicts"] == 1
    assert stats["errors"] == 1
    assert "existing non-managed recipe conflicts" in stats["error_messages"][0]

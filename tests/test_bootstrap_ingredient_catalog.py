from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import Ingredient
from api.services.bootstrap_ingredient_catalog import (
    load_bootstrap_ingredient_catalog,
    load_bootstrap_ingredient_catalogs,
    upsert_bootstrap_ingredient_catalogs,
)


class _ScalarResult:
    def __init__(self, all_=None):
        self._all = all_ or []

    def scalars(self):
        return self

    def all(self):
        return self._all


def test_load_bootstrap_ingredient_catalog_accepts_valid_yaml(
    tmp_path: pytest.TempPathFactory,
) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: core
    task_key_template: core
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: update
    is_default: true
    expected_duration_sec: 30
    timeout_duration_sec: 120
""".strip(),
        encoding="utf-8",
    )

    items, errors = load_bootstrap_ingredient_catalog(str(catalog))
    assert errors == []
    assert len(items) == 1
    assert items[0]["execution_target"] == "rackspace_core"
    assert items[0]["execution_engine"] == "bakery"
    assert items[0]["is_default"] is True
    assert items[0]["execution_parameters"] == {"operation": "update"}


def test_load_bootstrap_ingredient_catalog_rejects_noncanonical_target(
    tmp_path: pytest.TempPathFactory,
) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: create_ticket
    task_key_template: create_ticket
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        title: hello
        description: world
    execution_parameters:
      operation: open
""".strip(),
        encoding="utf-8",
    )

    items, errors = load_bootstrap_ingredient_catalog(str(catalog))
    assert items == []
    assert len(errors) == 1
    assert "execution_target must be one of" in errors[0]


@pytest.mark.asyncio
async def test_upsert_bootstrap_ingredient_catalogs_creates_and_updates(tmp_path) -> None:
    catalog_dir = tmp_path / "ingredients"
    catalog_dir.mkdir()
    (catalog_dir / "catalog.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: core
    task_key_template: rackspace_core.update
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: update
    is_default: true
    expected_duration_sec: 30
    timeout_duration_sec: 120
    retry_count: 1
    retry_delay: 5
    on_failure: continue
  - execution_target: jira
    task_key_template: jira.notify
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: notify
    expected_duration_sec: 10
    timeout_duration_sec: 60
    retry_count: 0
    retry_delay: 5
    on_failure: stop
""".strip(),
        encoding="utf-8",
    )
    (catalog_dir / "ignore.txt").write_text("noop\n", encoding="utf-8")

    existing = SimpleNamespace(
        execution_target="jira",
        destination_target="",
        task_key_template="jira.notify",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_id=None,
        execution_payload={"template": {"context": {"source": "old"}}},
        execution_parameters=None,
        is_default=False,
        is_blocking=True,
        expected_duration_sec=5,
        timeout_duration_sec=30,
        retry_count=0,
        retry_delay=1,
        on_failure="continue",
        deleted=True,
        deleted_at="2026-01-01",
        updated_at=None,
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(all_=[existing]))
    db.add = Mock()
    db.commit = AsyncMock(return_value=None)

    stats = await upsert_bootstrap_ingredient_catalogs(db, ingredients_dir=str(catalog_dir))

    assert stats["created"] == 1
    assert stats["updated"] == 1
    assert stats["skipped"] == 0
    assert stats["errors"] == 0
    assert stats["files_scanned"] == 1
    created_rows = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Ingredient)
    ]
    assert len(created_rows) == 1
    assert created_rows[0].execution_target == "rackspace_core"
    assert created_rows[0].task_key_template == "rackspace_core.update"
    assert existing.execution_payload == {"template": {"context": {"source": "test"}}}
    assert existing.execution_parameters == {"operation": "notify"}
    assert existing.deleted is False
    assert existing.deleted_at is None


def test_load_bootstrap_ingredient_catalogs_reads_multiple_yaml_files(tmp_path) -> None:
    catalog_dir = tmp_path / "ingredients"
    nested_dir = catalog_dir / "nested"
    nested_dir.mkdir(parents=True)
    (catalog_dir / "a.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: core
    task_key_template: rackspace_core.open
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: open
""".strip(),
        encoding="utf-8",
    )
    (nested_dir / "b.yml").write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: jira
    task_key_template: jira.notify
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: notify
""".strip(),
        encoding="utf-8",
    )
    (nested_dir / "ignore.json").write_text("{}", encoding="utf-8")

    items, errors, files_scanned = load_bootstrap_ingredient_catalogs(str(catalog_dir))

    assert errors == []
    assert files_scanned == 2
    assert {item["execution_target"] for item in items} == {"jira", "rackspace_core"}
    assert {item["task_key_template"] for item in items} == {
        "jira.notify",
        "rackspace_core.open",
    }


def test_repo_bootstrap_ingredient_directory_contains_full_mixer_action_matrix() -> None:
    repo_dir = Path(__file__).resolve().parents[1] / "config" / "bootstrap" / "ingredients"

    items, errors, files_scanned = load_bootstrap_ingredient_catalogs(str(repo_dir))

    assert errors == []
    assert files_scanned == 28
    assert len(items) == 28
    assert {item["execution_target"] for item in items} == {
        "discord",
        "github",
        "jira",
        "pagerduty",
        "rackspace_core",
        "servicenow",
        "teams",
    }
    assert {item["execution_parameters"]["operation"] for item in items} == {
        "close",
        "notify",
        "open",
        "update",
    }
    assert {item["task_key_template"] for item in items} == {
        f"{target}.{action}"
        for target in (
            "discord",
            "github",
            "jira",
            "pagerduty",
            "rackspace_core",
            "servicenow",
            "teams",
        )
        for action in ("open", "notify", "update", "close")
    }


@pytest.mark.asyncio
async def test_upsert_bootstrap_ingredient_catalogs_is_idempotent_for_existing_matrix(tmp_path) -> None:
    catalog_dir = tmp_path / "ingredients"
    nested_dir = catalog_dir / "rackspace_core"
    nested_dir.mkdir(parents=True)
    (nested_dir / "update.yaml").write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: rackspace_core
    task_key_template: rackspace_core.update
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: poundcake
    execution_parameters:
      operation: update
    is_default: true
    is_blocking: false
    expected_duration_sec: 15
    timeout_duration_sec: 120
    retry_count: 1
    retry_delay: 5
    on_failure: continue
""".strip(),
        encoding="utf-8",
    )

    existing = SimpleNamespace(
        execution_target="rackspace_core",
        destination_target="",
        task_key_template="rackspace_core.update",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_id=None,
        execution_payload={"template": {"context": {"source": "poundcake"}}},
        execution_parameters={"operation": "update"},
        is_default=True,
        is_blocking=False,
        expected_duration_sec=15,
        timeout_duration_sec=120,
        retry_count=1,
        retry_delay=5,
        on_failure="continue",
        deleted=False,
        deleted_at=None,
        updated_at=None,
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(all_=[existing]))
    db.add = Mock()
    db.commit = AsyncMock(return_value=None)

    stats = await upsert_bootstrap_ingredient_catalogs(db, ingredients_dir=str(catalog_dir))

    assert stats["created"] == 0
    assert stats["updated"] == 0
    assert stats["skipped"] == 1
    assert stats["errors"] == 0
    assert stats["files_scanned"] == 1
    db.add.assert_not_called()


def test_load_bootstrap_ingredient_catalog_legacy_single_file_still_works(tmp_path) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: core
    task_key_template: core
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        context:
          source: test
    execution_parameters:
      operation: ticket_create
""".strip(),
        encoding="utf-8",
    )

    items, errors = load_bootstrap_ingredient_catalog(str(catalog))

    assert errors == []
    assert len(items) == 1

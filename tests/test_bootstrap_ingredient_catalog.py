from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import Ingredient
from api.services.bootstrap_ingredient_catalog import (
    load_bootstrap_ingredient_catalog,
    upsert_bootstrap_bakery_ingredients,
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
  - execution_target: tickets.create
    task_key_template: create_ticket
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        title: hello
        description: world
    expected_duration_sec: 30
    timeout_duration_sec: 120
""".strip(),
        encoding="utf-8",
    )

    items, errors = load_bootstrap_ingredient_catalog(str(catalog))
    assert errors == []
    assert len(items) == 1
    assert items[0]["execution_target"] == "tickets.create"
    assert items[0]["execution_engine"] == "bakery"


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
""".strip(),
        encoding="utf-8",
    )

    items, errors = load_bootstrap_ingredient_catalog(str(catalog))
    assert items == []
    assert len(errors) == 1
    assert "execution_target must be one of" in errors[0]


@pytest.mark.asyncio
async def test_upsert_bootstrap_bakery_ingredients_creates_and_updates(tmp_path) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        """
apiVersion: poundcake/v1
kind: IngredientCatalog
ingredients:
  - execution_target: tickets.create
    task_key_template: create_ticket
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        title: hello
        description: world
    expected_duration_sec: 30
    timeout_duration_sec: 120
    retry_count: 1
    retry_delay: 5
    on_failure: continue
  - execution_target: tickets.comment
    task_key_template: comment_ticket
    execution_engine: bakery
    execution_purpose: comms
    execution_payload:
      template:
        comment: ping
    expected_duration_sec: 10
    timeout_duration_sec: 60
    retry_count: 0
    retry_delay: 5
    on_failure: stop
""".strip(),
        encoding="utf-8",
    )

    existing = SimpleNamespace(
        execution_target="tickets.comment",
        task_key_template="comment_ticket_old",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_id=None,
        execution_payload={"template": {"comment": "old"}},
        execution_parameters=None,
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

    stats = await upsert_bootstrap_bakery_ingredients(db, file_path=str(catalog))

    assert stats["created"] == 1
    assert stats["updated"] == 1
    assert stats["skipped"] == 0
    assert stats["errors"] == 0
    created_rows = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Ingredient)
    ]
    assert len(created_rows) == 1
    assert created_rows[0].execution_target == "tickets.create"
    assert existing.task_key_template == "comment_ticket"
    assert existing.execution_payload == {"template": {"comment": "ping"}}
    assert existing.deleted is False
    assert existing.deleted_at is None

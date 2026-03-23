from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from api.models.models import Ingredient
from api.services import dishwasher_service


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


def _stackstorm_action(
    *, ref: str = "core.local", name: str = "local", action_id: str = "action-1"
):
    return {
        "ref": ref,
        "name": name,
        "id": action_id,
        "parameters": {"cmd": {"type": "string", "required": True}},
        "description": "Execute a local command",
    }


def _ingredient(
    *, ingredient_id: int, execution_target: str, task_key_template: str, execution_id: str | None
):
    return Ingredient(
        id=ingredient_id,
        execution_target=execution_target,
        task_key_template=task_key_template,
        execution_id=execution_id,
        execution_payload={"old": True},
        execution_parameters={"old": True},
        execution_engine="stackstorm",
        execution_purpose="remediation",
        is_blocking=True,
        expected_duration_sec=60,
        timeout_duration_sec=300,
        retry_count=0,
        retry_delay=5,
        on_failure="stop",
        deleted=False,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_upsert_ingredients_prefers_exact_identity_match_over_target_only_match() -> None:
    canonical = _ingredient(
        ingredient_id=1,
        execution_target="core.local",
        task_key_template="local",
        execution_id="old-action-id",
    )
    temporary = _ingredient(
        ingredient_id=2,
        execution_target="core.local",
        task_key_template="echo_temp",
        execution_id=None,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecResult([temporary, canonical]))
    added: list[Ingredient] = []
    db.add = Mock(side_effect=added.append)

    stats = await dishwasher_service.upsert_ingredients(
        db, [_stackstorm_action(action_id="new-action-id")]
    )

    assert stats == {"created": 0, "updated": 1, "pruned": 0}
    assert added == []
    assert canonical.execution_id == "new-action-id"
    assert canonical.task_key_template == "local"
    assert temporary.execution_id is None
    assert temporary.task_key_template == "echo_temp"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_ingredients_creates_canonical_row_when_only_target_collision_exists() -> None:
    temporary = _ingredient(
        ingredient_id=2,
        execution_target="core.local",
        task_key_template="echo_temp",
        execution_id=None,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecResult([temporary]))
    added: list[Ingredient] = []
    db.add = Mock(side_effect=added.append)

    stats = await dishwasher_service.upsert_ingredients(db, [_stackstorm_action()])

    assert stats == {"created": 1, "updated": 0, "pruned": 0}
    assert len(added) == 1
    assert added[0].execution_target == "core.local"
    assert added[0].task_key_template == "local"
    assert added[0].execution_id == "action-1"
    assert temporary.execution_id is None
    assert temporary.task_key_template == "echo_temp"
    db.commit.assert_awaited_once()

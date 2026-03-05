from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models.models import DishIngredient, Order
from api.services.execution_types import ExecutionResult


class ScalarResult:
    def __init__(self, first=None, all_=None, scalar=None):
        self._first = first
        self._all = all_ or []
        self._scalar = scalar

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all

    def scalar(self):
        return self._scalar

    def unique(self):
        return self


class _BeginContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    with patch("api.core.database.SessionLocal") as mock_session:
        mock_db = AsyncMock()
        mock_db.add = Mock()
        mock_db.begin = Mock(return_value=_BeginContext())
        mock_db.refresh = AsyncMock(return_value=None)
        mock_db.flush = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_db


def _make_resolving_order(order_id: int = 1) -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="resolved",
        processing_status="resolving",
        is_active=True,
        alert_group_name="group",
        severity="critical",
        instance="host1",
        counter=1,
        bakery_ticket_id=None,
        bakery_operation_id=None,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        bakery_comms_id=None,
        labels={"alertname": "a"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )


def test_create_ingredient_accepts_object_execution_payload(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=None))
    mock_db_session.add = Mock()

    async def _refresh(ingredient):
        now = datetime.now(timezone.utc)
        ingredient.id = 77
        ingredient.created_at = now
        ingredient.updated_at = now
        ingredient.is_default = False
        ingredient.deleted = False
        ingredient.deleted_at = None

    mock_db_session.refresh = AsyncMock(side_effect=_refresh)

    payload = {
        "execution_target": "core.local",
        "task_key_template": "core.local",
        "execution_engine": "stackstorm",
        "execution_payload": {"template": {"foo": "bar"}, "context": {"a": 1}},
        "expected_duration_sec": 30,
    }
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["execution_payload"] == {"template": {"foo": "bar"}, "context": {"a": 1}}


def test_create_ingredient_rejects_string_execution_payload_with_422(client, mock_db_session):
    payload = {
        "execution_target": "core.local",
        "task_key_template": "core.local",
        "execution_engine": "stackstorm",
        "execution_payload": "not-object",
        "expected_duration_sec": 30,
    }
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 422


def test_create_ingredient_persists_is_default_true(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=None))
    mock_db_session.add = Mock()

    async def _refresh(ingredient):
        now = datetime.now(timezone.utc)
        ingredient.id = 90
        ingredient.created_at = now
        ingredient.updated_at = now
        ingredient.deleted = False
        ingredient.deleted_at = None

    mock_db_session.refresh = AsyncMock(side_effect=_refresh)

    payload = {
        "execution_target": "core.default",
        "task_key_template": "core.default",
        "execution_engine": "bakery",
        "execution_purpose": "comms",
        "execution_payload": {"template": {"context": {"source": "test"}}},
        "execution_parameters": {"operation": "ticket_update"},
        "is_default": True,
        "expected_duration_sec": 30,
    }
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["is_default"] is True


def test_create_ingredient_accepts_deprecated_aliases_and_returns_canonical_fields(
    client, mock_db_session
):
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=None))
    mock_db_session.add = Mock()

    async def _refresh(ingredient):
        now = datetime.now(timezone.utc)
        ingredient.id = 88
        ingredient.created_at = now
        ingredient.updated_at = now
        ingredient.is_default = False
        ingredient.deleted = False
        ingredient.deleted_at = None

    mock_db_session.refresh = AsyncMock(side_effect=_refresh)

    payload = {
        "execution_target": "legacy.alias",
        "task_key_template": "legacy.alias",
        "execution_engine": "stackstorm",
        "action_id": "legacy-id",
        "ingredient_kind": "utility",
        "execution_payload": {"template": {"foo": "bar"}},
        "expected_duration_sec": 30,
    }
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["execution_id"] == "legacy-id"
    assert body["action_id"] == "legacy-id"
    assert body["execution_purpose"] == "utility"
    assert body["ingredient_kind"] == "utility"


def test_update_ingredient_rejects_array_execution_payload_with_422(client, mock_db_session):
    payload = {"execution_payload": ["bad"]}
    response = client.put("/api/v1/ingredients/1", json=payload)
    assert response.status_code == 422


def test_create_ingredient_allows_same_target_for_different_engines(client, mock_db_session):
    existing = SimpleNamespace(id=9)
    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=None),
            ScalarResult(first=existing),
        ]
    )
    mock_db_session.add = Mock()

    async def _refresh(ingredient):
        now = datetime.now(timezone.utc)
        ingredient.id = 89
        ingredient.created_at = now
        ingredient.updated_at = now
        ingredient.is_default = False
        ingredient.deleted = False
        ingredient.deleted_at = None

    mock_db_session.refresh = AsyncMock(side_effect=_refresh)

    payload = {
        "execution_target": "shared.target",
        "task_key_template": "shared.target",
        "execution_engine": "stackstorm",
        "execution_payload": {"template": {"foo": "bar"}},
        "expected_duration_sec": 30,
    }
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 201

    payload["execution_engine"] = "bakery"
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 201

    payload["execution_engine"] = "stackstorm"
    response = client.post("/api/v1/ingredients/", json=payload)
    assert response.status_code == 400


def test_resolve_order_with_valid_bakery_comms_payload_seeds_pending_step(client, mock_db_session):
    order = _make_resolving_order()
    order.bakery_ticket_id = "ticket-1"
    ingredient = SimpleNamespace(
        task_key_template="comment_ticket",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="core",
        execution_payload={"template": {"comment": "resolved"}},
        execution_parameters={"operation": "ticket_comment", "visibility": "internal"},
        on_failure="stop",
    )
    recipe_ingredient = SimpleNamespace(
        id=12,
        step_order=1,
        run_phase="resolving",
        execution_parameters_override={"context": {"order_id": 1}},
        ingredient=ingredient,
    )
    recipe = SimpleNamespace(id=9, recipe_ingredients=[recipe_ingredient])

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=recipe),  # recipe
            ScalarResult(first=None),  # dish lookup
            ScalarResult(scalar=10),  # expected duration
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with patch(
        "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
        new=AsyncMock(
            return_value=ExecutionResult(
                engine="bakery",
                status="succeeded",
                execution_ref="op-1",
                raw={"status": "succeeded"},
            )
        ),
    ):
        response = client.post("/api/v1/orders/1/resolve")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "complete"

    added_rows = [call.args[0] for call in mock_db_session.add.call_args_list]
    dish_ingredients = [row for row in added_rows if isinstance(row, DishIngredient)]
    assert len(dish_ingredients) == 1
    assert dish_ingredients[0].execution_status == "succeeded"
    assert dish_ingredients[0].execution_payload == {
        "comment": "resolved",
        "operation": "ticket_comment",
        "visibility": "internal",
        "context": {"order_id": 1},
    }


def test_resolve_order_with_invalid_bakery_comms_payload_fails_order(client, mock_db_session):
    order = _make_resolving_order()
    ingredient = SimpleNamespace(
        task_key_template="close_ticket",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="core",
        execution_payload={"context": {"missing_template": True}},
        execution_parameters={"operation": "ticket_close"},
        on_failure="stop",
    )
    recipe_ingredient = SimpleNamespace(
        id=13,
        step_order=1,
        run_phase="resolving",
        execution_parameters_override=None,
        ingredient=ingredient,
    )
    recipe = SimpleNamespace(id=10, recipe_ingredients=[recipe_ingredient])

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=recipe),  # recipe
            ScalarResult(first=None),  # dish lookup
            ScalarResult(scalar=10),  # expected duration
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with patch(
        "api.services.execution_orchestrator.ExecutionOrchestrator.execute",
        new=AsyncMock(
            return_value=ExecutionResult(
                engine="bakery",
                status="succeeded",
                execution_ref="op-2",
                raw={"status": "succeeded"},
            )
        ),
    ):
        response = client.post("/api/v1/orders/1/resolve")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "failed"

    added_rows = [call.args[0] for call in mock_db_session.add.call_args_list]
    dish_ingredients = [row for row in added_rows if isinstance(row, DishIngredient)]
    assert len(dish_ingredients) == 1
    assert dish_ingredients[0].execution_status == "failed"
    assert "execution_payload.template" in str(dish_ingredients[0].error_message)


def test_resolve_order_with_invalid_payload_and_on_failure_continue_keeps_order_complete(
    client, mock_db_session
):
    order = _make_resolving_order()
    ingredient = SimpleNamespace(
        task_key_template="comment_ticket",
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="core",
        execution_payload={"context": {"invalid": True}},
        execution_parameters={"operation": "ticket_comment"},
        on_failure="continue",
    )
    recipe_ingredient = SimpleNamespace(
        id=14,
        step_order=1,
        run_phase="resolving",
        execution_parameters_override=None,
        ingredient=ingredient,
    )
    recipe = SimpleNamespace(id=11, recipe_ingredients=[recipe_ingredient])

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),
            ScalarResult(first=recipe),
            ScalarResult(first=None),
            ScalarResult(scalar=10),
            ScalarResult(all_=[]),
        ]
    )

    response = client.post("/api/v1/orders/1/resolve")
    assert response.status_code == 200
    assert response.json()["processing_status"] == "complete"

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from api.main import app
from api.models.models import Dish, Order


class ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first

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
        mock_db.begin = Mock(return_value=_BeginContext())
        mock_db.refresh = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_db


def _make_order(order_id: int = 1, status: str = "processing") -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status=status,
        is_active=True,
        alert_group_name="group",
        severity="warning",
        instance="localhost",
        counter=1,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": "A"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_dish(dish_id: int = 1, status: str = "processing") -> Dish:
    now = datetime.now(timezone.utc)
    return Dish(
        id=dish_id,
        req_id="REQ-1",
        order_id=1,
        recipe_id=1,
        processing_status=status,
        execution_status="running",
        started_at=now,
        completed_at=None,
        expected_duration_sec=10,
        actual_duration_sec=None,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )


def test_terminal_dish_sets_order_to_resolving(client, mock_db_session):
    dish = _make_dish()
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    with patch("api.api.dishes._sync_bakery_for_terminal_dish", new=AsyncMock()):
        response = client.put("/api/v1/dishes/1", json={"processing_status": "complete"})

    assert response.status_code == 200
    assert order.processing_status == "resolving"
    assert order.is_active is True


def test_bulk_upsert_dedupes_by_step_identity(client, mock_db_session):
    ri = SimpleNamespace(
        id=11,
        step_order=1,
        ingredient=SimpleNamespace(task_key_template="core.local"),
    )
    dish = SimpleNamespace(id=1, recipe=SimpleNamespace(recipe_ingredients=[ri]))

    captured: dict[str, object] = {}

    class _FakeInsert:
        def __init__(self):
            self.inserted = SimpleNamespace(
                task_key="i_task_key",
                execution_engine="i_execution_engine",
                execution_target="i_execution_target",
                execution_ref="i_execution_ref",
                execution_payload={"key": "i_execution_payload"},
                execution_parameters="i_execution_parameters",
                execution_status="i_execution_status",
                attempt="i_attempt",
                started_at="i_started_at",
                completed_at="i_completed_at",
                canceled_at="i_canceled_at",
                result="i_result",
                error_message="i_error_message",
                updated_at="i_updated_at",
                recipe_ingredient_id="i_recipe_ingredient_id",
            )

        def values(self, rows):
            captured["rows"] = rows
            return self

        def on_duplicate_key_update(self, **kwargs):
            captured["update"] = kwargs
            return "UPSERT_STMT"

    async def _execute(stmt, *args, **kwargs):
        if captured.get("rows") is None:
            return ScalarResult(first=dish)
        assert stmt == "UPSERT_STMT"
        return SimpleNamespace(rowcount=1)

    mock_db_session.execute = AsyncMock(side_effect=_execute)

    with patch("api.api.dishes.mysql_insert", return_value=_FakeInsert()):
        response = client.post(
            "/api/v1/dishes/1/ingredients/bulk",
            json={
                "items": [
                    {
                        "task_key": "step_1_core_local",
                        "execution_ref": "exec-a",
                        "execution_status": "running",
                    },
                    {
                        "task_key": "step_1_core_local",
                        "execution_ref": "exec-b",
                        "execution_status": "succeeded",
                    },
                ]
            },
        )

    assert response.status_code == 200
    rows = captured["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["recipe_ingredient_id"] == 11


def test_bulk_upsert_unknown_task_uses_step_identity_fallback(client, mock_db_session):
    dish = SimpleNamespace(id=1, recipe=SimpleNamespace(recipe_ingredients=[]))

    captured: dict[str, object] = {}

    class _FakeInsert:
        def __init__(self):
            self.inserted = SimpleNamespace(
                task_key="i_task_key",
                execution_engine="i_execution_engine",
                execution_target="i_execution_target",
                execution_ref="i_execution_ref",
                execution_payload={"key": "i_execution_payload"},
                execution_parameters="i_execution_parameters",
                execution_status="i_execution_status",
                attempt="i_attempt",
                started_at="i_started_at",
                completed_at="i_completed_at",
                canceled_at="i_canceled_at",
                result="i_result",
                error_message="i_error_message",
                updated_at="i_updated_at",
                recipe_ingredient_id="i_recipe_ingredient_id",
            )

        def values(self, rows):
            captured["rows"] = rows
            return self

        def on_duplicate_key_update(self, **kwargs):
            return "UPSERT_STMT"

    async def _execute(stmt, *args, **kwargs):
        if captured.get("rows") is None:
            return ScalarResult(first=dish)
        return SimpleNamespace(rowcount=1)

    mock_db_session.execute = AsyncMock(side_effect=_execute)

    with patch("api.api.dishes.mysql_insert", return_value=_FakeInsert()):
        response = client.post(
            "/api/v1/dishes/1/ingredients/bulk",
            json={"items": [{"execution_ref": "unknown-exec", "execution_status": "succeeded"}]},
        )

    assert response.status_code == 200
    rows = captured["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["recipe_ingredient_id"] is None
    assert rows[0]["task_key"] == "unknown-exec"


@pytest.mark.skipif(
    not os.getenv("POUNDCAKE_MARIADB_TEST_URL"),
    reason="set POUNDCAKE_MARIADB_TEST_URL to run DB-level concurrency test",
)
def test_atomic_upsert_concurrency_db_level():
    engine = create_engine(os.environ["POUNDCAKE_MARIADB_TEST_URL"], future=True)
    table_name = f"tmp_dish_ingredients_{uuid.uuid4().hex[:8]}"
    upsert_sql = text(f"""
        INSERT INTO {table_name}
            (dish_id, recipe_ingredient_id, task_key, execution_ref, execution_status, updated_at)
        VALUES
            (:dish_id, :recipe_ingredient_id, :task_key, :execution_ref, :execution_status, UTC_TIMESTAMP(6))
        ON DUPLICATE KEY UPDATE
            execution_ref = VALUES(execution_ref),
            execution_status = VALUES(execution_status),
            updated_at = VALUES(updated_at)
        """)

    with engine.begin() as conn:
        conn.execute(text(f"""
                CREATE TABLE {table_name} (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dish_id BIGINT NOT NULL,
                    recipe_ingredient_id BIGINT NULL,
                    task_key VARCHAR(255) NULL,
                    recipe_ingredient_id_norm BIGINT GENERATED ALWAYS AS (IFNULL(recipe_ingredient_id, 0)) STORED,
                    task_key_norm VARCHAR(255) GENERATED ALWAYS AS (IFNULL(task_key, '')) STORED,
                    execution_ref VARCHAR(100) NULL,
                    execution_status VARCHAR(50) NULL,
                    updated_at DATETIME(6) NOT NULL,
                    UNIQUE KEY ux_dish_step (dish_id, recipe_ingredient_id_norm, task_key_norm)
                )
                """))

    errors: list[Exception] = []

    def _worker(worker_id: int) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(
                    upsert_sql,
                    {
                        "dish_id": 7,
                        "recipe_ingredient_id": 3,
                        "task_key": "step_1_core_local",
                        "execution_ref": f"exec-{worker_id}",
                        "execution_status": "succeeded",
                    },
                )
        except Exception as exc:  # pragma: no cover - best effort collection
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                    SELECT COUNT(*) AS cnt, MIN(execution_status) AS status, MIN(execution_ref) AS execution_ref
                    FROM {table_name}
                    WHERE dish_id = 7
                      AND IFNULL(recipe_ingredient_id, 0) = 3
                      AND IFNULL(task_key, '') = 'step_1_core_local'
                    """)).mappings().first()
            assert row is not None
            assert row["cnt"] == 1
            assert row["status"] == "succeeded"
            assert row["execution_ref"]
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        engine.dispose()

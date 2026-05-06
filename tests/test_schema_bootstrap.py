from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from api.scripts import bootstrap_schema


def _load_baseline_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/2026_02_03_1600_initial_schema.py"
    )
    spec = importlib.util.spec_from_file_location("poundcake_initial_schema_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeAlembicOp:
    def __init__(self) -> None:
        self.tables: set[str] = set()
        self.indexes: set[tuple[str, str]] = set()
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, str]] = []

    def f(self, name: str) -> str:
        return name

    def create_table(self, table_name: str, *args, **kwargs) -> None:
        self.tables.add(table_name)
        self.created_tables.append(table_name)

    def create_index(self, index_name: str, table_name: str, columns, **kwargs) -> None:
        self.indexes.add((table_name, str(index_name)))
        self.created_indexes.append((table_name, str(index_name)))

    def execute(self, statement: str) -> None:
        if "CREATE TABLE orders" in statement:
            self.create_table("orders")


def _patch_baseline_inspection(module: ModuleType, fake_op: _FakeAlembicOp, monkeypatch) -> None:
    monkeypatch.setattr(module, "op", fake_op)
    monkeypatch.setattr(module, "_table_exists", lambda table_name: table_name in fake_op.tables)
    monkeypatch.setattr(
        module,
        "_index_exists",
        lambda table_name, index_name: (table_name, str(index_name)) in fake_op.indexes,
    )


def test_initial_schema_creates_tables_from_empty_database(monkeypatch):
    module = _load_baseline_module()
    fake_op = _FakeAlembicOp()
    _patch_baseline_inspection(module, fake_op, monkeypatch)

    module.upgrade()

    assert "recipes" in fake_op.created_tables
    assert "orders" in fake_op.created_tables
    assert "auth_role_bindings" in fake_op.created_tables
    assert ("recipes", "ix_recipes_name") in fake_op.created_indexes


def test_initial_schema_finishes_unstamped_partial_database(monkeypatch):
    module = _load_baseline_module()
    fake_op = _FakeAlembicOp()
    fake_op.tables.update(
        {
            "recipes",
            "ingredients",
            "recipe_ingredients",
            "orders",
            "dishes",
            "dish_ingredients",
            "order_communications",
            "bakery_monitor_state",
            "watchdog_heartbeat_state",
            "release_update_notifications",
            "release_update_notification_deliveries",
        }
    )
    _patch_baseline_inspection(module, fake_op, monkeypatch)

    module.upgrade()

    assert "recipes" not in fake_op.created_tables
    assert "release_update_notifications" not in fake_op.created_tables
    assert "alert_suppressions" in fake_op.created_tables
    assert "auth_principals" in fake_op.created_tables
    assert "auth_role_bindings" in fake_op.created_tables


def test_initial_schema_index_names_fit_mysql_identifier_limit():
    module = _load_baseline_module()
    fake_op = _FakeAlembicOp()

    module.op = fake_op
    module._table_exists = lambda table_name: table_name in fake_op.tables
    module._index_exists = (
        lambda table_name, index_name: (table_name, str(index_name)) in fake_op.indexes
    )

    module.upgrade()

    assert fake_op.created_indexes
    assert max(len(index_name) for _, index_name in fake_op.created_indexes) <= 64
    assert ("release_update_notification_deliveries", "ix_relupd_deliv_comm_id") in (
        fake_op.created_indexes
    )
    assert ("release_update_notification_deliveries", "ix_relupd_deliv_op_id") in (
        fake_op.created_indexes
    )


def _write_revision(database_url: str, revision: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )


def test_schema_bootstrap_runs_baseline_for_empty_database(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"
    calls: list[SimpleNamespace] = []

    monkeypatch.setattr(bootstrap_schema, "get_sync_database_url", lambda: database_url)
    monkeypatch.setattr(bootstrap_schema, "get_alembic_config", lambda: SimpleNamespace())

    def fake_upgrade(config, revision):
        calls.append(SimpleNamespace(config=config, revision=revision))
        _write_revision(database_url, bootstrap_schema.BASELINE_REVISION)

    monkeypatch.setattr(bootstrap_schema.command, "upgrade", fake_upgrade)

    bootstrap_schema.ensure_baseline_schema()

    assert [call.revision for call in calls] == ["head"]
    assert bootstrap_schema.get_current_revisions(database_url) == [
        bootstrap_schema.BASELINE_REVISION
    ]


def test_schema_bootstrap_runs_baseline_for_unstamped_partial_database(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'partial.db'}"
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE recipes (id INTEGER PRIMARY KEY)"))

    monkeypatch.setattr(bootstrap_schema, "get_sync_database_url", lambda: database_url)
    monkeypatch.setattr(bootstrap_schema, "get_alembic_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        bootstrap_schema.command,
        "upgrade",
        lambda config, revision: _write_revision(database_url, bootstrap_schema.BASELINE_REVISION),
    )

    bootstrap_schema.ensure_baseline_schema()

    assert bootstrap_schema.get_current_revisions(database_url) == [
        bootstrap_schema.BASELINE_REVISION
    ]


def test_schema_bootstrap_skips_already_stamped_database(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'stamped.db'}"
    _write_revision(database_url, bootstrap_schema.BASELINE_REVISION)

    monkeypatch.setattr(bootstrap_schema, "get_sync_database_url", lambda: database_url)
    monkeypatch.setattr(bootstrap_schema.command, "upgrade", lambda config, revision: pytest.fail())

    bootstrap_schema.ensure_baseline_schema()


def test_schema_bootstrap_rejects_unexpected_revision(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'unexpected.db'}"
    _write_revision(database_url, "legacy_revision")

    monkeypatch.setattr(bootstrap_schema, "get_sync_database_url", lambda: database_url)

    with pytest.raises(RuntimeError, match="Unexpected Alembic revision"):
        bootstrap_schema.ensure_baseline_schema()

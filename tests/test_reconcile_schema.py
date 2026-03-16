"""Regression tests for stamped-database schema reconciliation."""

from __future__ import annotations

from unittest.mock import Mock

from api.scripts import reconcile_schema


class _BeginContext:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    def __enter__(self) -> object:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_reconcile_schema_creates_missing_auth_tables(monkeypatch) -> None:
    conn = Mock()
    engine = Mock()
    engine.begin.return_value = _BeginContext(conn)
    engine.dispose = Mock()

    monkeypatch.setenv("POUNDCAKE_DATABASE_URL", "mysql+pymysql://user:pass@db/poundcake")
    monkeypatch.setattr(reconcile_schema, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(
        reconcile_schema,
        "_table_exists",
        lambda _conn, table_name: table_name not in {"auth_principals", "auth_role_bindings"},
    )
    monkeypatch.setattr(reconcile_schema, "_column_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(reconcile_schema, "_index_exists", lambda *_args, **_kwargs: True)

    create_all = Mock()
    monkeypatch.setattr(reconcile_schema.Base.metadata, "create_all", create_all)

    reconcile_schema.reconcile_schema()

    create_all.assert_called_once()
    called_tables = create_all.call_args.kwargs["tables"]
    assert [table.name for table in called_tables] == ["auth_principals", "auth_role_bindings"]
    engine.dispose.assert_called_once()


def test_reconcile_schema_skips_table_creation_when_auth_tables_exist(monkeypatch) -> None:
    conn = Mock()
    engine = Mock()
    engine.begin.return_value = _BeginContext(conn)
    engine.dispose = Mock()

    monkeypatch.setenv("POUNDCAKE_DATABASE_URL", "mysql+pymysql://user:pass@db/poundcake")
    monkeypatch.setattr(reconcile_schema, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(reconcile_schema, "_table_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(reconcile_schema, "_column_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(reconcile_schema, "_index_exists", lambda *_args, **_kwargs: True)

    create_all = Mock()
    monkeypatch.setattr(reconcile_schema.Base.metadata, "create_all", create_all)

    reconcile_schema.reconcile_schema()

    create_all.assert_not_called()
    engine.dispose.assert_called_once()

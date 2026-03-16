from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock

structlog_stub = types.ModuleType("structlog")
setattr(structlog_stub, "configure", lambda **_: None)
setattr(structlog_stub, "get_logger", lambda: Mock())
setattr(
    structlog_stub,
    "stdlib",
    types.SimpleNamespace(
        add_log_level=object(),
        BoundLogger=object,
        LoggerFactory=lambda: object(),
    ),
)
setattr(
    structlog_stub,
    "processors",
    types.SimpleNamespace(
        TimeStamper=lambda **_: object(),
        JSONRenderer=lambda: object(),
    ),
)
sys.modules.setdefault("structlog", structlog_stub)

db_init = importlib.import_module("bakery.db_init")


def test_determine_migration_strategy_upgrades_empty_schema() -> None:
    assert db_init.determine_migration_strategy(set()) == "upgrade"


def test_determine_migration_strategy_upgrades_versioned_schema() -> None:
    assert (
        db_init.determine_migration_strategy(
            {"messages", "ticket_requests", "mixer_configs", "alembic_version"},
            ["001"],
        )
        == "upgrade"
    )


def test_determine_migration_strategy_stamps_when_version_table_is_empty() -> None:
    assert (
        db_init.determine_migration_strategy(
            {"messages", "ticket_requests", "mixer_configs", "alembic_version"},
            [],
        )
        == "stamp"
    )


def test_determine_migration_strategy_stamps_complete_unversioned_schema() -> None:
    assert (
        db_init.determine_migration_strategy({"messages", "ticket_requests", "mixer_configs"})
        == "stamp"
    )


def test_determine_migration_strategy_rejects_partial_unversioned_schema() -> None:
    assert db_init.determine_migration_strategy({"messages"}) == "error"


def test_run_migrations_stamps_existing_unversioned_schema(monkeypatch) -> None:
    fake_config = Mock()
    stamp = Mock()
    upgrade = Mock()

    monkeypatch.setattr(db_init, "Config", Mock(return_value=fake_config))
    monkeypatch.setattr(
        db_init,
        "inspect_schema_state",
        Mock(return_value=({"messages", "ticket_requests", "mixer_configs"}, [])),
    )
    monkeypatch.setattr(db_init.command, "stamp", stamp)
    monkeypatch.setattr(db_init.command, "upgrade", upgrade)

    assert db_init.run_migrations() is True
    stamp.assert_called_once_with(fake_config, "head")
    upgrade.assert_not_called()


def test_run_migrations_fails_for_partial_unversioned_schema(monkeypatch) -> None:
    fake_config = Mock()
    stamp = Mock()
    upgrade = Mock()

    monkeypatch.setattr(db_init, "Config", Mock(return_value=fake_config))
    monkeypatch.setattr(
        db_init,
        "inspect_schema_state",
        Mock(return_value=({"messages"}, [])),
    )
    monkeypatch.setattr(db_init.command, "stamp", stamp)
    monkeypatch.setattr(db_init.command, "upgrade", upgrade)

    assert db_init.run_migrations() is False
    stamp.assert_not_called()
    upgrade.assert_not_called()

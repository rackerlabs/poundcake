from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock

structlog_stub = types.ModuleType("structlog")
structlog_stub.configure = lambda **_: None
structlog_stub.get_logger = lambda: Mock()
structlog_stub.stdlib = types.SimpleNamespace(
    add_log_level=object(),
    BoundLogger=object,
    LoggerFactory=lambda: object(),
)
structlog_stub.processors = types.SimpleNamespace(
    TimeStamper=lambda **_: object(),
    JSONRenderer=lambda: object(),
)
sys.modules.setdefault("structlog", structlog_stub)

db_init = importlib.import_module("bakery.db_init")


def test_run_migrations_upgrades_head(monkeypatch) -> None:
    fake_config = Mock()
    upgrade = Mock()

    monkeypatch.setattr(db_init, "Config", Mock(return_value=fake_config))
    monkeypatch.setattr(db_init.command, "upgrade", upgrade)

    assert db_init.run_migrations() is True
    upgrade.assert_called_once_with(fake_config, "head")

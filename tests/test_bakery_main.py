"""Bakery application route regression tests."""

from __future__ import annotations

import importlib
import sys
import types

from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    sys.modules.pop("bakery.main", None)
    fake_structlog = types.SimpleNamespace(
        configure=lambda **kwargs: None,
        get_logger=lambda *args, **kwargs: types.SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
        stdlib=types.SimpleNamespace(
            filter_by_level=object(),
            add_logger_name=object(),
            add_log_level=object(),
            PositionalArgumentsFormatter=lambda *a, **k: object(),
            BoundLogger=object,
            LoggerFactory=lambda *a, **k: object(),
        ),
        processors=types.SimpleNamespace(
            TimeStamper=lambda *a, **k: object(),
            StackInfoRenderer=lambda *a, **k: object(),
            format_exc_info=object(),
            UnicodeDecoder=lambda *a, **k: object(),
            JSONRenderer=lambda *a, **k: object(),
        ),
    )
    monkeypatch.setitem(sys.modules, "structlog", fake_structlog)
    return importlib.import_module("bakery.main").app


def test_bakery_openapi_exposes_communications_only(monkeypatch) -> None:
    app = _load_app(monkeypatch)
    openapi = app.openapi()
    paths = set(openapi.get("paths", {}))
    tags = {tag["name"] for tag in openapi.get("tags", [])}

    assert "/api/v1/communications" in paths
    assert not any(path.startswith("/api/v1/tickets") for path in paths)
    assert "communications" in tags
    assert "tickets" not in tags


def test_legacy_ticket_routes_return_404(monkeypatch) -> None:
    app = _load_app(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/v1/tickets")

    assert response.status_code == 404

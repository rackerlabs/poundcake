"""Unit tests for kitchen.prep_chef."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest


def _reload_prep_chef(monkeypatch: pytest.MonkeyPatch):
    module_name = "kitchen.prep_chef"
    if module_name in sys.modules:
        del sys.modules[module_name]

    fake_http_client = types.ModuleType("api.core.http_client")
    setattr(
        fake_http_client,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, json=lambda: [], text=""),
    )

    fake_logging = types.ModuleType("api.core.logging")
    setattr(fake_logging, "setup_logging", lambda: None)
    setattr(
        fake_logging,
        "get_logger",
        lambda _name: SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            debug=lambda *_args, **_kwargs: None,
        ),
    )

    fake_config = types.ModuleType("api.core.config")
    setattr(fake_config, "get_settings", lambda: SimpleNamespace(poller_http_retries=3))

    fake_service_helpers = types.ModuleType("kitchen.service_helpers")
    setattr(fake_service_helpers, "wait_for_api", lambda *_args, **_kwargs: None)

    monkeypatch.setitem(sys.modules, "api.core.http_client", fake_http_client)
    monkeypatch.setitem(sys.modules, "api.core.logging", fake_logging)
    monkeypatch.setitem(sys.modules, "api.core.config", fake_config)
    monkeypatch.setitem(sys.modules, "kitchen.service_helpers", fake_service_helpers)

    return importlib.import_module(module_name)


def test_prep_interval_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREP_INTERVAL", "9")
    prep_chef = _reload_prep_chef(monkeypatch)

    assert prep_chef.PREP_INTERVAL == 9


def test_prep_interval_defaults_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PREP_INTERVAL", raising=False)
    prep_chef = _reload_prep_chef(monkeypatch)

    assert prep_chef.PREP_INTERVAL == 5


def test_prep_loop_sleeps_using_prep_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    prep_chef = _reload_prep_chef(monkeypatch)
    monkeypatch.setattr(prep_chef, "PREP_INTERVAL", 7)
    monkeypatch.setattr(prep_chef, "POLL_LIMIT", 1)

    monkeypatch.setattr(
        prep_chef,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=500, text="boom", json=lambda: {}),
    )

    sleep_calls: list[int] = []

    def _sleep(interval: int) -> None:
        sleep_calls.append(interval)
        raise RuntimeError("stop loop")

    monkeypatch.setattr(prep_chef.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop loop"):
        prep_chef.prep_loop()

    assert sleep_calls
    assert all(call == 7 for call in sleep_calls)

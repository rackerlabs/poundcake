"""Unit tests for kitchen.service_helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import kitchen.service_helpers as service_helpers


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_wait_for_api_returns_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()

    monkeypatch.setattr(
        service_helpers,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: _Resp(200),
    )

    ok = service_helpers.wait_for_api(
        "http://api:8000/api/v1", "SYSTEM-TEST", logger, max_attempts=1
    )

    assert ok is True
    logger.info.assert_called()


def test_wait_for_api_allows_503_when_health_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()

    monkeypatch.setattr(
        service_helpers,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: _Resp(503),
    )

    ok = service_helpers.wait_for_api(
        "http://api:8000/api/v1",
        "SYSTEM-TEST",
        logger,
        max_attempts=1,
        require_healthy=False,
    )

    assert ok is True


def test_wait_for_api_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()
    attempts = iter([RuntimeError("boom"), RuntimeError("boom"), _Resp(200)])
    sleep_calls: list[float] = []

    def _request(*_args, **_kwargs):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(service_helpers, "request_with_retry_sync", _request)
    monkeypatch.setattr(service_helpers.time, "sleep", lambda sec: sleep_calls.append(sec))
    monkeypatch.setattr(
        service_helpers, "get_settings", lambda: SimpleNamespace(poller_http_retries=3)
    )

    ok = service_helpers.wait_for_api(
        "http://api:8000/api/v1",
        "SYSTEM-TEST",
        logger,
        max_attempts=3,
        delay_sec=0.25,
    )

    assert ok is True
    assert sleep_calls == [0.25, 0.25]


def test_wait_for_api_returns_false_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        service_helpers,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: _Resp(503),
    )
    monkeypatch.setattr(service_helpers.time, "sleep", lambda sec: sleep_calls.append(sec))
    monkeypatch.setattr(
        service_helpers, "get_settings", lambda: SimpleNamespace(poller_http_retries=1)
    )

    ok = service_helpers.wait_for_api(
        "http://api:8000/api/v1",
        "SYSTEM-TEST",
        logger,
        max_attempts=3,
        delay_sec=0.5,
        require_healthy=True,
    )

    assert ok is False
    assert sleep_calls == [0.5, 0.5]
    logger.warning.assert_called_once()

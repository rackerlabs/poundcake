"""Unit tests for kitchen.dishwasher."""

from __future__ import annotations

import pytest

import kitchen.dishwasher as dishwasher


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def test_run_sync_success_uses_mark_bootstrap_param(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _request(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _Resp(200, {"synced": 3})

    monkeypatch.setattr(dishwasher, "MARK_BOOTSTRAP", True)
    monkeypatch.setattr(dishwasher, "request_with_retry_sync", _request)

    ok = dishwasher.run_sync()

    assert ok is True
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/cook/sync")
    assert captured["params"] == {"mark_bootstrap": "true"}


def test_run_sync_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dishwasher, "MARK_BOOTSTRAP", False)
    monkeypatch.setattr(
        dishwasher,
        "request_with_retry_sync",
        lambda *_args, **_kwargs: _Resp(500, text="error"),
    )

    assert dishwasher.run_sync() is False


def test_main_bootstrap_retries_then_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dishwasher, "DISHWASHER_INTERVAL", 0)
    monkeypatch.setattr(dishwasher, "wait_for_api", lambda *_args, **_kwargs: None)

    attempts = iter([False, False, True])
    run_calls = {"count": 0}
    sleeps: list[float] = []

    def _run_sync() -> bool:
        run_calls["count"] += 1
        return next(attempts)

    monkeypatch.setattr(dishwasher, "run_sync", _run_sync)
    monkeypatch.setenv("DISHWASHER_BOOTSTRAP_ATTEMPTS", "3")
    monkeypatch.setenv("DISHWASHER_BOOTSTRAP_RETRY_DELAY", "0.1")
    monkeypatch.setattr(dishwasher.time, "sleep", lambda sec: sleeps.append(sec))

    dishwasher.main()

    assert run_calls["count"] == 3
    assert sleeps == [0.1, 0.1]


def test_main_periodic_mode_runs_and_sleeps_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dishwasher, "DISHWASHER_INTERVAL", 2)
    monkeypatch.setattr(dishwasher, "wait_for_api", lambda *_args, **_kwargs: None)

    run_calls = {"count": 0}
    sleep_calls: list[int] = []

    def _run_sync() -> bool:
        run_calls["count"] += 1
        return True

    def _sleep(seconds: int) -> None:
        sleep_calls.append(seconds)
        raise SystemExit

    monkeypatch.setattr(dishwasher, "run_sync", _run_sync)
    monkeypatch.setattr(dishwasher.time, "sleep", _sleep)

    with pytest.raises(SystemExit):
        dishwasher.main()

    assert run_calls["count"] == 1
    assert sleep_calls == [2]

"""Unit tests for kitchen.timer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import kitchen.timer as timer


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_update_dish_final_status_sets_duration_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=12)).isoformat()
    dish = {"id": 7, "started_at": started_at}
    captured: dict[str, object] = {}

    def _request(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _Resp(200, {"id": 7})

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)

    ok = timer.update_dish(
        dish,
        req_id="REQ-7",
        processing_status="complete",
        status="succeeded",
        final_status=True,
    )

    assert ok is True
    assert captured["method"] == "PUT"
    assert str(captured["url"]).endswith("/dishes/7")
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["processing_status"] == "complete"
    assert payload["status"] == "succeeded"
    assert "completed_at" in payload
    assert payload["actual_duration_sec"] >= 10


def test_check_for_timeouts_hard_timeout_cancels_and_fails_dish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    dish = {
        "id": 9,
        "started_at": started_at,
        "expected_duration_sec": 2,
        "workflow_execution_id": "exec-9",
    }

    called: dict[str, object] = {}

    def _cancel(execution_id: str, req_id: str) -> bool:
        called["cancel"] = (execution_id, req_id)
        return True

    def _update(d, req_id: str, **kwargs) -> bool:
        called["update"] = (d, req_id, kwargs)
        return True

    monkeypatch.setattr(timer, "cancel_execution", _cancel)
    monkeypatch.setattr(timer, "update_dish", _update)

    timed_out = timer.check_for_timeouts(dish, "REQ-9")

    assert timed_out is True
    assert called["cancel"] == ("exec-9", "REQ-9")
    _dish, req_id, kwargs = called["update"]
    assert req_id == "REQ-9"
    assert kwargs["processing_status"] == "failed"
    assert kwargs["status"] == "timeout"
    assert kwargs["final_status"] is True


def test_monitor_dishes_marks_abandoned_when_execution_missing_in_st2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 15,
        "req_id": "REQ-15",
        "workflow_execution_id": "exec-15",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    update_calls: list[tuple[dict, str, dict]] = []

    def _update(d: dict, req_id: str, **kwargs) -> bool:
        update_calls.append((d, req_id, kwargs))
        return True

    steps = iter(
        [
            _Resp(200, [dish]),  # processing dishes
            _Resp(200, []),  # finalizing dishes
            _Resp(200, dish),  # finalize-claim
            _Resp(404, {"faultstring": "not found"}),  # st2 execution lookup
        ]
    )

    def _request(_method: str, _url: str, **_kwargs):
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-15"
    assert kwargs["processing_status"] == "failed"
    assert kwargs["status"] == "abandoned"
    assert kwargs["error_msg"] == "ST2 execution not found"
    assert kwargs["final_status"] is True


def test_monitor_dishes_terminal_success_persists_ingredients_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 20,
        "req_id": "REQ-20",
        "workflow_execution_id": "exec-20",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
    }
    claimed_dish = {**dish}
    tasks = [
        {
            "id": "task-2",
            "task_id": "step2",
            "status": "succeeded",
            "result": {"stdout": "two"},
            "start_timestamp": "2026-02-13T10:00:05Z",
            "end_timestamp": "2026-02-13T10:00:07Z",
        },
        {
            "id": "task-1",
            "task_id": "step1",
            "status": "succeeded",
            "result": {"stdout": "one"},
            "start_timestamp": "2026-02-13T10:00:01Z",
            "end_timestamp": "2026-02-13T10:00:04Z",
        },
    ]

    update_calls: list[tuple[dict, str, dict]] = []
    ingredient_bulk_posts: list[dict] = []

    def _update(d: dict, req_id: str, **kwargs) -> bool:
        update_calls.append((d, req_id, kwargs))
        return True

    steps = iter(
        [
            _Resp(200, [dish]),  # processing dishes
            _Resp(200, []),  # finalizing dishes
            _Resp(200, claimed_dish),  # finalize-claim
            _Resp(200, {"status": "succeeded", "result": {"tasks": tasks}}),  # execution
            _Resp(200, []),  # existing dish ingredients
            _Resp(200, {"ok": True}),  # bulk ingredient write
        ]
    )

    def _request(method: str, url: str, **kwargs):
        if method == "POST" and str(url).endswith("/ingredients/bulk"):
            ingredient_bulk_posts.append(kwargs.get("json"))
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(ingredient_bulk_posts) == 1
    items = ingredient_bulk_posts[0]["items"]
    assert len(items) == 2
    assert items[0]["task_id"] == "step1"
    assert items[1]["task_id"] == "step2"

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-20"
    assert kwargs["processing_status"] == "complete"
    assert kwargs["status"] == "succeeded"
    assert kwargs["final_status"] is True
    assert kwargs["started_at"] == "2026-02-13T10:00:01Z"
    assert [task["task_id"] for task in kwargs["result"]] == ["step1", "step2"]


def test_monitor_dishes_missing_execution_id_times_out_to_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_created_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    dish = {
        "id": 21,
        "req_id": "REQ-21",
        "workflow_execution_id": None,
        "created_at": old_created_at,
        "started_at": None,
    }

    update_calls: list[tuple[dict, str, dict]] = []

    def _update(d: dict, req_id: str, **kwargs) -> bool:
        update_calls.append((d, req_id, kwargs))
        return True

    steps = iter(
        [
            _Resp(200, [dish]),  # processing dishes
            _Resp(200, []),  # finalizing dishes
            _Resp(200, dish),  # finalize-claim
        ]
    )

    def _request(_method: str, _url: str, **_kwargs):
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "MISSING_EXECUTION_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-21"
    assert kwargs["processing_status"] == "failed"
    assert kwargs["status"] == "abandoned"
    assert kwargs["error_msg"] == "Missing workflow execution id"
    assert kwargs["final_status"] is True

"""Unit tests for kitchen.timer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

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


def test_update_dish__final_status__sets_duration_and_completion(
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
        execution_status="succeeded",
        final_status=True,
    )

    assert ok is True
    assert captured["method"] == "PUT"
    assert str(captured["url"]).endswith("/dishes/7")
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["processing_status"] == "complete"
    assert payload["execution_status"] == "succeeded"
    assert "completed_at" in payload
    assert payload["actual_duration_sec"] >= 10


def test_check_for_timeouts__hard_timeout__cancels_and_fails_dish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    dish = {
        "id": 9,
        "started_at": started_at,
        "expected_duration_sec": 2,
        "execution_ref": "exec-9",
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
    _dish, req_id, kwargs = cast(tuple[object, str, dict[str, object]], called["update"])
    assert req_id == "REQ-9"
    assert kwargs["processing_status"] == "failed"
    assert kwargs["execution_status"] == "timeout"
    assert kwargs["final_status"] is True


def test_monitor_dishes__missing_st2_execution__marks_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 15,
        "req_id": "REQ-15",
        "execution_ref": "exec-15",
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
    assert kwargs["execution_status"] == "abandoned"
    assert kwargs["error_msg"] == "ST2 execution not found"
    assert kwargs["final_status"] is True


def test_monitor_dishes__terminal_success__persists_ingredients_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 20,
        "req_id": "REQ-20",
        "execution_ref": "exec-20",
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
            _Resp(200, []),  # bakery-stage ingredient fetch (no bakery rows)
        ]
    )

    def _request(method: str, url: str, **kwargs):
        if method == "POST" and str(url).endswith("/ingredients/bulk"):
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                ingredient_bulk_posts.append(payload)
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(ingredient_bulk_posts) == 1
    items = ingredient_bulk_posts[0]["items"]
    assert len(items) == 2
    assert items[0]["task_key"] == "step1"
    assert items[1]["task_key"] == "step2"

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-20"
    assert kwargs["processing_status"] == "complete"
    assert kwargs["execution_status"] == "succeeded"
    assert kwargs["final_status"] is True
    assert kwargs["started_at"] == "2026-02-13T10:00:01Z"
    assert [task["task_key"] for task in kwargs["result"]] == ["step1", "step2"]


def test_monitor_dishes__non_terminal_execution_returns_dish_to_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 24,
        "req_id": "REQ-24",
        "execution_ref": "exec-24",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
    }
    claimed_dish = {**dish, "processing_status": "finalizing"}
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
            _Resp(
                200,
                {
                    "status": "running",
                    "result": {
                        "tasks": [
                            {
                                "id": "task-24",
                                "task_id": "step1",
                                "status": "running",
                                "result": {"stdout": "still going"},
                                "start_timestamp": "2026-02-13T10:00:01Z",
                                "end_timestamp": None,
                            }
                        ]
                    },
                },
            ),  # execution
            _Resp(200, []),  # existing dish ingredients
            _Resp(200, {"ok": True}),  # bulk ingredient write
        ]
    )

    def _request(method: str, url: str, **kwargs):
        if method == "POST" and str(url).endswith("/ingredients/bulk"):
            ingredient_bulk_posts.append(kwargs.get("json") or {})
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(ingredient_bulk_posts) == 1
    assert ingredient_bulk_posts[0]["items"][0]["execution_status"] == "running"

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-24"
    assert kwargs["processing_status"] == "processing"
    assert kwargs["execution_status"] == "running"
    assert kwargs["final_status"] is False
    assert kwargs["started_at"] == "2026-02-13T10:00:01Z"
    assert kwargs["result"][0]["task_key"] == "step1"


def test_monitor_dishes__terminal_success_requeues_when_more_segments_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 22,
        "req_id": "REQ-22",
        "execution_ref": "exec-22",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "recipe": {
            "recipe_ingredients": [
                {"id": 1, "step_order": 1},
                {"id": 2, "step_order": 2},
            ]
        },
    }
    claimed_dish = {**dish}
    patch_calls: list[dict] = []
    update_calls: list[tuple[dict, str, dict]] = []

    def _update(d: dict, req_id: str, **kwargs) -> bool:
        update_calls.append((d, req_id, kwargs))
        return True

    steps = iter(
        [
            _Resp(200, [dish]),
            _Resp(200, []),
            _Resp(200, claimed_dish),
            _Resp(
                200,
                {
                    "status": "succeeded",
                    "result": {
                        "tasks": [
                            {
                                "id": "task-1",
                                "task_id": "step_1_ping",
                                "status": "succeeded",
                                "result": {"stdout": "ok"},
                                "start_timestamp": "2026-02-13T10:00:01Z",
                                "end_timestamp": "2026-02-13T10:00:02Z",
                            }
                        ]
                    },
                },
            ),
            _Resp(200, []),
            _Resp(200, {"ok": True}),
            _Resp(
                200,
                [
                    {
                        "recipe_ingredient_id": 1,
                        "task_key": "step_1_ping",
                        "execution_engine": "stackstorm",
                        "execution_status": "succeeded",
                    },
                    {
                        "recipe_ingredient_id": 2,
                        "task_key": "step_2_update",
                        "execution_engine": "bakery",
                        "execution_status": "pending",
                    },
                ],
            ),
            _Resp(200, {"id": 22}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        if method == "PATCH" and str(url).endswith("/dishes/22"):
            patch_calls.append(kwargs.get("json") or {})
        return next(steps)

    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert update_calls == []
    assert patch_calls == [
        {
            "processing_status": "new",
            "execution_status": None,
            "execution_ref": None,
            "error_message": None,
            "result": [
                {
                    "id": "task-1",
                    "task_key": "step_1_ping",
                    "status": "succeeded",
                    "result": {"stdout": "ok"},
                    "start_timestamp": "2026-02-13T10:00:01Z",
                    "end_timestamp": "2026-02-13T10:00:02Z",
                }
            ],
            "started_at": "2026-02-13T10:00:01Z",
        }
    ]


def test_monitor_dishes__missing_execution_id_after_timeout__marks_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_created_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    dish = {
        "id": 21,
        "req_id": "REQ-21",
        "execution_ref": None,
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
            _Resp(
                200,
                [
                    {
                        "task_key": "step1",
                        "execution_engine": "stackstorm",
                        "execution_status": "pending",
                    }
                ],
            ),  # ingredients include stackstorm, so missing execution id timeout path applies
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
    assert kwargs["execution_status"] == "abandoned"
    assert kwargs["error_msg"] == "Missing workflow execution id"
    assert kwargs["final_status"] is True

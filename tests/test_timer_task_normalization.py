"""Regression tests for StackStorm task payload normalization in kitchen.timer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import kitchen.timer as timer


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def test_monitor_dishes_normalizes_task_name_and_action_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 31,
        "req_id": "REQ-31",
        "execution_ref": "exec-31",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
    }

    tasks = [
        {
            "id": "task-exec-31",
            "name": "step_1_local",
            "status": "succeeded",
            "result": {"stdout": "single step test"},
            "start_timestamp": "2026-03-03T01:57:23.634000Z",
            "end_timestamp": "2026-03-03T01:57:23.686000Z",
            "action_executions": [{"id": "69a640038d77dff9f77ea0a9"}],
        }
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
            _Resp(200, dish),  # finalize-claim
            _Resp(200, {"status": "succeeded", "result": {}}),  # execution
            _Resp(200, tasks),  # execution tasks
            _Resp(200, []),  # existing dish ingredients
            _Resp(200, {"updated": 1}),  # bulk ingredient write
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
    assert len(items) == 1
    assert items[0]["task_key"] == "step_1_local"
    assert items[0]["execution_ref"] == "task-exec-31"
    assert items[0]["execution_status"] == "succeeded"
    assert items[0]["completed_at"] == "2026-03-03T01:57:23.686000Z"

    assert len(update_calls) == 1
    _updated_dish, req_id, kwargs = update_calls[0]
    assert req_id == "REQ-31"
    assert kwargs["processing_status"] == "complete"
    assert kwargs["execution_status"] == "succeeded"
    assert kwargs["final_status"] is True
    assert kwargs["started_at"] == "2026-03-03T01:57:23.634000Z"

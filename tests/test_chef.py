"""Unit tests for kitchen.chef."""

from __future__ import annotations

import pytest

import kitchen.chef as chef


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def test_run_chef_marks_dish_failed_for_unsupported_recipe_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    steps = iter(
        [
            _Resp(200, [{"id": 1, "req_id": "REQ-1"}]),
            _Resp(
                200,
                {
                    "id": 1,
                    "req_id": "REQ-1",
                    "recipe": {"id": 10, "source_type": "github", "workflow_parameters": {}},
                },
            ),
            _Resp(200, {"ok": True}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return next(steps)

    monkeypatch.setattr(chef, "wait_for_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chef, "request_with_retry_sync", _request)
    monkeypatch.setattr(chef.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit))

    with pytest.raises(SystemExit):
        chef.run_chef()

    assert any(
        method == "PATCH"
        and url.endswith("/dishes/1")
        and body
        and body.get("processing_status") == "failed"
        and "Unsupported recipe source_type" in body.get("error_message", "")
        for method, url, body in calls
    )


def test_run_chef_executes_existing_workflow_and_patches_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    steps = iter(
        [
            _Resp(200, [{"id": 2, "req_id": "REQ-2"}]),
            _Resp(
                200,
                {
                    "id": 2,
                    "req_id": "REQ-2",
                    "recipe": {
                        "id": 11,
                        "source_type": "stackstorm",
                        "workflow_id": "wf.my_action",
                        "workflow_parameters": {"foo": "bar"},
                    },
                },
            ),
            _Resp(200, {"name": "wf.my_action"}),
            _Resp(201, {"id": "st2-exec-1"}),
            _Resp(200, {"id": 2}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        try:
            return next(steps)
        except StopIteration:
            raise SystemExit

    monkeypatch.setattr(chef, "wait_for_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chef, "request_with_retry_sync", _request)

    with pytest.raises(SystemExit):
        chef.run_chef()

    assert any(
        method == "POST"
        and url.endswith("/cook/execute")
        and body == {"action": "wf.my_action", "parameters": {"foo": "bar"}}
        for method, url, body in calls
    )
    assert any(
        method == "PATCH"
        and url.endswith("/dishes/2")
        and body == {"workflow_execution_id": "st2-exec-1"}
        for method, url, body in calls
    )

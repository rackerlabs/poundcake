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


def test_run_chef_register_failure_marks_dish_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None, dict | None]] = []
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
            _Resp(
                200,
                [
                    {
                        "recipe_ingredient_id": 1,
                        "task_key": "step_1_ping",
                        "execution_engine": "stackstorm",
                        "execution_target": "linux.ping",
                        "execution_status": "pending",
                    }
                ],
            ),
            _Resp(500, {"detail": "register failed"}, text="register failed"),
            _Resp(200, {"ok": True}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("json"), kwargs.get("headers")))
        return next(steps)

    monkeypatch.setattr(chef, "wait_for_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chef, "request_with_retry_sync", _request)
    monkeypatch.setattr(chef.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit))
    monkeypatch.setenv("POUNDCAKE_INTERNAL_API_KEY", "worker-key")

    with pytest.raises(SystemExit):
        chef.run_chef()

    assert any(
        method == "PATCH"
        and url.endswith("/dishes/1")
        and body
        and body.get("processing_status") == "failed"
        and "register failed" in body.get("error_message", "")
        and headers
        and headers.get("X-Internal-API-Key") == "worker-key"
        for method, url, body, headers in calls
    )


def test_run_chef_executes_registered_workflow_and_patches_execution_ref(
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
                        "recipe_ingredients": [
                            {
                                "id": 10,
                                "ingredient": {
                                    "execution_engine": "stackstorm",
                                    "execution_target": "linux.ping",
                                },
                            }
                        ],
                    },
                },
            ),
            _Resp(
                200,
                [
                    {
                        "recipe_ingredient_id": 10,
                        "task_key": "step_1_linux_ping",
                        "execution_engine": "stackstorm",
                        "execution_target": "linux.ping",
                        "execution_status": "pending",
                    }
                ],
            ),
            _Resp(200, {"workflow_id": "poundcake.wf_my_action"}),
            _Resp(
                201, {"execution_ref": "st2-exec-1", "status": "running", "engine": "stackstorm"}
            ),
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
        and body
        and body.get("execution_engine") == "stackstorm"
        and body.get("execution_target") == "poundcake.wf_my_action"
        and body.get("execution_parameters") == {}
        for method, url, body in calls
    )
    assert any(
        method == "PATCH" and url.endswith("/dishes/2") and body == {"execution_ref": "st2-exec-1"}
        for method, url, body in calls
    )

"""Regression tests for missing-workflow execute retries in kitchen.chef."""

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


def _missing_workflow_error(path_suffix: str = "AutomatedTestRecipe-1.yaml") -> str:
    return (
        "[Errno 2] No such file or directory: "
        f"'/opt/stackstorm/packs/poundcake/actions/workflows/{path_suffix}'"
    )


def test_run_chef_retries_execute_when_workflow_file_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    steps = iter(
        [
            _Resp(200, [{"id": 11, "req_id": "REQ-11"}]),
            _Resp(200, {"id": 11, "req_id": "REQ-11", "recipe": {"name": "AutomatedTestRecipe-1"}}),
            _Resp(
                200,
                [
                    {
                        "recipe_ingredient_id": 1,
                        "task_key": "step_1_task",
                        "execution_engine": "stackstorm",
                        "execution_target": "poundcake.AutomatedTestRecipe-1",
                        "execution_status": "pending",
                    }
                ],
            ),
            _Resp(200, {"workflow_id": "poundcake.AutomatedTestRecipe-1"}),
            _Resp(
                200,
                {
                    "status": "failed",
                    "engine": "stackstorm",
                    "error_message": _missing_workflow_error(),
                },
            ),
            _Resp(201, {"execution_ref": "exec-11", "status": "running", "engine": "stackstorm"}),
            _Resp(200, {"id": 11}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        calls.append((method, str(url), kwargs.get("json")))
        try:
            return next(steps)
        except StopIteration:
            raise SystemExit

    monkeypatch.setattr(chef, "wait_for_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chef, "request_with_retry_sync", _request)
    monkeypatch.setattr(chef.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(chef, "CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES", 2)
    monkeypatch.setattr(chef, "CHEF_EXECUTE_MISSING_WORKFLOW_RETRY_BACKOFF_SECONDS", 0.01)

    with pytest.raises(SystemExit):
        chef.run_chef()

    execute_calls = [
        (method, url, body)
        for method, url, body in calls
        if method == "POST" and url.endswith("/cook/execute")
    ]
    assert len(execute_calls) == 2
    assert execute_calls[0][2] == {
        "execution_engine": "stackstorm",
        "execution_target": "poundcake.AutomatedTestRecipe-1",
        "execution_parameters": {},
    }

    assert any(
        method == "PATCH" and url.endswith("/dishes/11") and body == {"execution_ref": "exec-11"}
        for method, url, body in calls
    )


def test_run_chef_does_not_retry_non_missing_execute_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    steps = iter(
        [
            _Resp(200, [{"id": 12, "req_id": "REQ-12"}]),
            _Resp(200, {"id": 12, "req_id": "REQ-12", "recipe": {"name": "AutomatedTestRecipe-2"}}),
            _Resp(
                200,
                [
                    {
                        "recipe_ingredient_id": 1,
                        "task_key": "step_1_task",
                        "execution_engine": "stackstorm",
                        "execution_target": "poundcake.AutomatedTestRecipe-2",
                        "execution_status": "pending",
                    }
                ],
            ),
            _Resp(200, {"workflow_id": "poundcake.AutomatedTestRecipe-2"}),
            _Resp(200, {"status": "failed", "engine": "stackstorm", "error_message": "boom"}),
            _Resp(200, {"id": 12}),
        ]
    )

    def _request(method: str, url: str, **kwargs):
        calls.append((method, str(url), kwargs.get("json")))
        return next(steps)

    monkeypatch.setattr(chef, "wait_for_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chef, "request_with_retry_sync", _request)
    monkeypatch.setattr(chef.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit))
    monkeypatch.setattr(chef, "CHEF_EXECUTE_MISSING_WORKFLOW_RETRIES", 2)

    with pytest.raises(SystemExit):
        chef.run_chef()

    execute_calls = [
        (method, url, body)
        for method, url, body in calls
        if method == "POST" and url.endswith("/cook/execute")
    ]
    assert len(execute_calls) == 1

    assert any(
        method == "PATCH"
        and url.endswith("/dishes/12")
        and body
        and body.get("processing_status") == "failed"
        and "boom" in str(body.get("error_message"))
        for method, url, body in calls
    )

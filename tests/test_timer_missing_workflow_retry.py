"""Unit tests for missing-workflow-file retry behavior in kitchen.timer."""

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


def _missing_workflow_error(path_suffix: str = "AutomatedTestRecipe-1.yaml") -> str:
    return (
        "[Errno 2] No such file or directory: "
        f"'/opt/stackstorm/packs/poundcake/actions/workflows/{path_suffix}'"
    )


def test_missing_workflow_failure_retries_once_and_rebinds_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 31,
        "req_id": "REQ-31",
        "workflow_execution_id": "exec-old",
        "retry_attempt": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe": {"workflow_id": "poundcake.auto-31", "workflow_parameters": {"x": "y"}},
    }
    updated: list[dict] = []
    called_urls: list[str] = []
    execute_headers: dict | None = None

    def _request(method: str, url: str, **kwargs):
        nonlocal execute_headers
        called_urls.append(str(url))
        path = str(url)
        if path.endswith("/dishes"):
            status = (kwargs.get("params") or {}).get("processing_status")
            return _Resp(200, [dish] if status == "processing" else [])
        if path.endswith("/finalize-claim"):
            return _Resp(200, dish)
        if "/cook/executions/" in path and path.endswith("/tasks"):
            return _Resp(404, {"faultstring": "no tasks endpoint data"})
        if path.endswith("/cook/executions"):
            return _Resp(200, [])
        if "/cook/executions/" in path:
            return _Resp(200, {"status": "failed", "result": {"error": _missing_workflow_error()}})
        if path.endswith("/cook/execute") and method == "POST":
            execute_headers = kwargs.get("headers")
            return _Resp(201, {"id": "exec-new"})
        raise AssertionError(f"Unexpected request: {method} {path}")

    def _update(_dish: dict, _req_id: str, **kwargs) -> bool:
        updated.append(kwargs)
        return True

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)
    monkeypatch.setenv("POUNDCAKE_INTERNAL_API_KEY", "worker-key")

    timer.monitor_dishes()

    assert any(url.endswith("/cook/execute") for url in called_urls)
    assert len(updated) == 1
    assert updated[0]["processing_status"] == "processing"
    assert updated[0]["workflow_execution_id"] == "exec-new"
    assert updated[0]["retry_attempt"] == 1
    assert updated[0]["clear_error"] is True
    assert "final_status" not in updated[0]
    assert execute_headers is not None
    assert execute_headers.get("X-Request-ID") == "REQ-31"
    assert execute_headers.get("X-Internal-API-Key") == "worker-key"


def test_non_matching_failure_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 32,
        "req_id": "REQ-32",
        "workflow_execution_id": "exec-32",
        "retry_attempt": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe": {"workflow_id": "poundcake.auto-32", "workflow_parameters": {}},
    }
    updated: list[dict] = []
    called_urls: list[str] = []

    def _request(method: str, url: str, **kwargs):
        called_urls.append(str(url))
        path = str(url)
        if path.endswith("/dishes"):
            status = (kwargs.get("params") or {}).get("processing_status")
            return _Resp(200, [dish] if status == "processing" else [])
        if path.endswith("/finalize-claim"):
            return _Resp(200, dish)
        if "/cook/executions/" in path and path.endswith("/tasks"):
            return _Resp(404, {"faultstring": "no tasks endpoint data"})
        if path.endswith("/cook/executions"):
            return _Resp(200, [])
        if "/cook/executions/" in path:
            return _Resp(200, {"status": "failed", "result": {"error": "random stackstorm error"}})
        raise AssertionError(f"Unexpected request: {method} {path}")

    def _update(_dish: dict, _req_id: str, **kwargs) -> bool:
        updated.append(kwargs)
        return True

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert not any(url.endswith("/cook/execute") for url in called_urls)
    assert len(updated) == 1
    assert updated[0]["processing_status"] == "failed"
    assert updated[0]["final_status"] is True
    assert updated[0]["error_msg"] == "random stackstorm error"


def test_retry_attempt_one_does_not_retry_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 33,
        "req_id": "REQ-33",
        "workflow_execution_id": "exec-33",
        "retry_attempt": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe": {"workflow_id": "poundcake.auto-33", "workflow_parameters": {}},
    }
    updated: list[dict] = []
    called_urls: list[str] = []

    def _request(method: str, url: str, **kwargs):
        called_urls.append(str(url))
        path = str(url)
        if path.endswith("/dishes"):
            status = (kwargs.get("params") or {}).get("processing_status")
            return _Resp(200, [dish] if status == "processing" else [])
        if path.endswith("/finalize-claim"):
            return _Resp(200, dish)
        if "/cook/executions/" in path and path.endswith("/tasks"):
            return _Resp(404, {"faultstring": "no tasks endpoint data"})
        if path.endswith("/cook/executions"):
            return _Resp(200, [])
        if "/cook/executions/" in path:
            return _Resp(
                200, {"status": "failed", "result": {"error": _missing_workflow_error("x.yaml")}}
            )
        raise AssertionError(f"Unexpected request: {method} {path}")

    def _update(_dish: dict, _req_id: str, **kwargs) -> bool:
        updated.append(kwargs)
        return True

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert not any(url.endswith("/cook/execute") for url in called_urls)
    assert len(updated) == 1
    assert updated[0]["processing_status"] == "failed"
    assert updated[0]["final_status"] is True


def test_retry_execute_failure_falls_back_to_failed_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dish = {
        "id": 34,
        "req_id": "REQ-34",
        "workflow_execution_id": "exec-34",
        "retry_attempt": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe": {"workflow_id": "poundcake.auto-34", "workflow_parameters": {}},
    }
    updated: list[dict] = []

    def _request(method: str, url: str, **kwargs):
        path = str(url)
        if path.endswith("/dishes"):
            status = (kwargs.get("params") or {}).get("processing_status")
            return _Resp(200, [dish] if status == "processing" else [])
        if path.endswith("/finalize-claim"):
            return _Resp(200, dish)
        if "/cook/executions/" in path and path.endswith("/tasks"):
            return _Resp(404, {"faultstring": "no tasks endpoint data"})
        if path.endswith("/cook/executions"):
            return _Resp(200, [])
        if "/cook/executions/" in path:
            return _Resp(
                200, {"status": "failed", "result": {"error": _missing_workflow_error("y.yaml")}}
            )
        if path.endswith("/cook/execute") and method == "POST":
            return _Resp(500, {"faultstring": "boom"}, text="boom")
        raise AssertionError(f"Unexpected request: {method} {path}")

    def _update(_dish: dict, _req_id: str, **kwargs) -> bool:
        updated.append(kwargs)
        return True

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)
    monkeypatch.setattr(timer, "update_dish", _update)
    monkeypatch.setattr(timer, "check_for_timeouts", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timer.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(timer, "API_UNAVAILABLE_SINCE", None)

    timer.monitor_dishes()

    assert len(updated) == 1
    assert updated[0]["processing_status"] == "failed"
    assert updated[0]["final_status"] is True
    assert "workflow file retry failed" in str(updated[0]["error_msg"])
    assert "HTTP 500" in str(updated[0]["error_msg"])

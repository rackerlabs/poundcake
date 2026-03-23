from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.stackstorm_service import StackStormActionManager, StackStormClient


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_stackstorm_client_get_execution_normalizes_owned_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.stackstorm_service.get_settings",
        lambda: SimpleNamespace(
            stackstorm_url="http://st2.example",
            stackstorm_verify_ssl=False,
            external_http_retries=1,
            stackstorm_auth_token=None,
            get_stackstorm_api_key=lambda: "token",
        ),
    )
    client = StackStormClient()

    async def _request(*args, **kwargs):
        return _Resp(
            200,
            {
                "id": "exec-1",
                "action": "poundcake.filesystem",
                "status": "succeeded",
                "parent": "parent-1",
                "context": {"orquesta": {"task_id": "step_1"}},
                "start_timestamp": "2026-03-23T12:00:00Z",
                "end_timestamp": "2026-03-23T12:00:05Z",
                "result": {"stdout": "done"},
                "unexpected": "allowed internally",
            },
        )

    monkeypatch.setattr(client, "_request", _request)

    payload = await client.get_execution("exec-1")

    assert payload.id == "exec-1"
    assert payload.task_key == "step_1"
    assert payload.status == "succeeded"
    assert "unexpected" not in payload.model_dump()


@pytest.mark.asyncio
async def test_stackstorm_client_get_execution_tasks_normalizes_task_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.stackstorm_service.get_settings",
        lambda: SimpleNamespace(
            stackstorm_url="http://st2.example",
            stackstorm_verify_ssl=False,
            external_http_retries=1,
            stackstorm_auth_token=None,
            get_stackstorm_api_key=lambda: "token",
        ),
    )
    client = StackStormClient()

    async def _request(*args, **kwargs):
        return _Resp(
            200,
            [
                {
                    "name": "step_1",
                    "state": "succeeded",
                    "action_executions": [{"id": "task-exec-1"}],
                    "result": {"stdout": "ok"},
                    "start_timestamp": "2026-03-23T12:00:00Z",
                    "end_timestamp": "2026-03-23T12:00:02Z",
                    "extra": "ignored",
                }
            ],
        )

    monkeypatch.setattr(client, "_request", _request)

    payload = await client.get_execution_tasks("exec-1")

    assert len(payload) == 1
    assert payload[0].id == "task-exec-1"
    assert payload[0].task_key == "step_1"
    assert payload[0].status == "succeeded"


@pytest.mark.asyncio
async def test_stackstorm_action_manager_execution_history_normalizes_child_executions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.stackstorm_service.get_settings",
        lambda: SimpleNamespace(
            stackstorm_url="http://st2.example",
            stackstorm_verify_ssl=False,
            external_http_retries=1,
            stackstorm_auth_token=None,
            get_stackstorm_api_key=lambda: "token",
        ),
    )
    manager = StackStormActionManager(StackStormClient())

    async def _request(*args, **kwargs):
        return _Resp(
            200,
            [
                {
                    "id": "child-1",
                    "status": "running",
                    "parent": "exec-1",
                    "context": {"orquesta": {"task_id": "step_2"}},
                    "result": {"stdout": "in progress"},
                    "start_timestamp": "2026-03-23T12:00:01Z",
                    "end_timestamp": None,
                }
            ],
        )

    monkeypatch.setattr(manager, "_request", _request)

    payload = await manager.get_execution_history(parent="exec-1")

    assert len(payload) == 1
    assert payload[0].id == "child-1"
    assert payload[0].task_key == "step_2"
    assert payload[0].parent == "exec-1"

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.testclient import TestClient

from api.api.cook import router as cook_router
from api.services import stackstorm_service


class _Resp:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict:
        return self._json_data


def _build_app() -> FastAPI:
    app = FastAPI()

    class _ReqIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.req_id = "TEST-REQ-ID"
            return await call_next(request)

    app.add_middleware(_ReqIdMiddleware)
    app.include_router(cook_router, prefix="/api/v1")
    return app


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        stackstorm_url="http://st2.example",
        get_stackstorm_api_key=lambda: "test-api-key",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "wf-missing"},
        {"name": "wf-null", "execution_parameters": None},
    ],
)
def test_register_workflow_accepts_missing_or_null_execution_parameters(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
) -> None:
    monkeypatch.setenv("TESTING", "1")
    app = _build_app()
    client = TestClient(app)

    register_mock = AsyncMock(return_value="poundcake.wf")
    with (
        patch("api.api.cook.get_settings", return_value=_settings()),
        patch("api.api.cook.register_workflow_to_st2", register_mock),
    ):
        response = client.post("/api/v1/cook/workflows/register", json=payload)

    assert response.status_code == 200
    assert response.json() == {"workflow_id": "poundcake.wf"}


def test_register_workflow_rejects_non_object_execution_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTING", "1")
    app = _build_app()
    client = TestClient(app)

    error_message = "execution_parameters must be an object when provided"
    register_mock = AsyncMock(side_effect=ValueError(error_message))
    with (
        patch("api.api.cook.get_settings", return_value=_settings()),
        patch("api.api.cook.register_workflow_to_st2", register_mock),
    ):
        response = client.post(
            "/api/v1/cook/workflows/register",
            json={"name": "wf-bad", "execution_parameters": []},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": error_message}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recipe",
    [
        {"name": "wf-missing", "description": "desc"},
        {"name": "wf-null", "description": "desc", "execution_parameters": None},
    ],
)
async def test_register_workflow_to_st2_normalizes_missing_or_null_execution_parameters(
    monkeypatch: pytest.MonkeyPatch,
    recipe: dict,
) -> None:
    captured: dict[str, dict] = {}

    async def _request_with_retry(*_args, **kwargs):
        captured["payload"] = kwargs["json"]
        return _Resp(201, {"ref": "poundcake.wf"})

    monkeypatch.setattr(
        stackstorm_service,
        "get_settings",
        lambda: SimpleNamespace(
            stackstorm_pack_sync_register_retries=1,
            stackstorm_pack_sync_register_delay_seconds=1.0,
            external_http_retries=1,
        ),
    )
    monkeypatch.setattr(stackstorm_service, "request_with_retry", _request_with_retry)

    workflow_id = await stackstorm_service.register_workflow_to_st2(
        "http://st2.example", "test-api-key", recipe
    )

    assert workflow_id == "poundcake.wf"
    assert captured["payload"]["parameters"] == {}


@pytest.mark.asyncio
async def test_register_workflow_to_st2_preserves_object_execution_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, dict] = {}
    execution_parameters = {"foo": {"type": "string"}}

    async def _request_with_retry(*_args, **kwargs):
        captured["payload"] = kwargs["json"]
        return _Resp(201, {"ref": "poundcake.wf"})

    monkeypatch.setattr(
        stackstorm_service,
        "get_settings",
        lambda: SimpleNamespace(
            stackstorm_pack_sync_register_retries=1,
            stackstorm_pack_sync_register_delay_seconds=1.0,
            external_http_retries=1,
        ),
    )
    monkeypatch.setattr(stackstorm_service, "request_with_retry", _request_with_retry)

    await stackstorm_service.register_workflow_to_st2(
        "http://st2.example",
        "test-api-key",
        {
            "name": "wf-object",
            "description": "desc",
            "execution_parameters": execution_parameters,
        },
    )

    assert captured["payload"]["parameters"] == execution_parameters


@pytest.mark.asyncio
async def test_register_workflow_to_st2_rejects_non_object_execution_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def _request_with_retry(*_args, **_kwargs):
        nonlocal called
        called = True
        return _Resp(201, {"ref": "poundcake.wf"})

    monkeypatch.setattr(
        stackstorm_service,
        "get_settings",
        lambda: SimpleNamespace(
            stackstorm_pack_sync_register_retries=1,
            stackstorm_pack_sync_register_delay_seconds=1.0,
            external_http_retries=1,
        ),
    )
    monkeypatch.setattr(stackstorm_service, "request_with_retry", _request_with_retry)

    with pytest.raises(ValueError, match="execution_parameters must be an object when provided"):
        await stackstorm_service.register_workflow_to_st2(
            "http://st2.example",
            "test-api-key",
            {"name": "wf-bad", "description": "desc", "execution_parameters": ["bad"]},
        )

    assert called is False

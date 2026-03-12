import io
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.api.cook import router as cook_router
from api.api.auth import require_auth_if_enabled
from api.core.database import get_db
from api.services.stackstorm_service import build_stackstorm_pack_artifact
from api.version import __version__


def test_build_stackstorm_pack_artifact_contains_pack_yaml_and_workflows():
    recipes = [
        {
            "name": "My Workflow",
            "workflow_payload": {"version": "1.0", "tasks": {"t1": {"action": "core.noop"}}},
        }
    ]

    payload, etag = build_stackstorm_pack_artifact(recipes=recipes, pack_name="poundcake")

    assert payload
    assert etag.startswith('"') and etag.endswith('"')

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        names = sorted(archive.getnames())
        assert "pack.yaml" in names
        assert "actions/workflows/My_Workflow.yaml" in names
        pack_yaml = archive.extractfile("pack.yaml")
        assert pack_yaml is not None
        assert f'version: "{__version__}"' in pack_yaml.read().decode("utf-8")


def test_pack_artifact_endpoint_requires_token_and_supports_etag():
    app = FastAPI()
    app.include_router(cook_router, prefix="/api/v1")

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def unique(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeDB:
        async def execute(self, _stmt):
            return _Result(
                [
                    SimpleNamespace(
                        name="Recipe One",
                        workflow_payload={
                            "version": "1.0",
                            "tasks": {"x": {"action": "core.noop"}},
                        },
                    )
                ]
            )

    async def _fake_get_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = _fake_get_db

    client = TestClient(app)
    settings = SimpleNamespace(pack_sync_token="token123")

    with patch("api.services.pack_sync_service.get_settings", return_value=settings):
        denied = client.get("/api/v1/cook/packs")
        assert denied.status_code == 401

        ok = client.get(
            "/api/v1/cook/packs",
            headers={"X-Pack-Sync-Token": "token123"},
        )
        assert ok.status_code == 200
        assert ok.headers.get("etag")
        assert ok.headers.get("cache-control") == "no-cache"

        not_modified = client.get(
            "/api/v1/cook/packs",
            headers={
                "X-Pack-Sync-Token": "token123",
                "If-None-Match": ok.headers["etag"],
            },
        )
        assert not_modified.status_code == 304


def test_pack_artifact_endpoint_bypasses_session_auth_with_global_dependency(monkeypatch):
    app = FastAPI(dependencies=[Depends(require_auth_if_enabled)])
    app.include_router(cook_router, prefix="/api/v1")

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def unique(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeDB:
        async def execute(self, _stmt):
            return _Result(
                [
                    SimpleNamespace(
                        name="Recipe One",
                        workflow_payload={
                            "version": "1.0",
                            "tasks": {"x": {"action": "core.noop"}},
                        },
                    )
                ]
            )

    async def _fake_get_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = _fake_get_db
    client = TestClient(app)

    # Ensure auth dependency does not short-circuit in test mode.
    monkeypatch.setenv("TESTING", "")

    auth_settings = SimpleNamespace(
        testing=False,
        auth_enabled=True,
        auth_internal_api_key="",
    )
    pack_sync_settings = SimpleNamespace(pack_sync_token="token123")

    with (
        patch("api.api.auth.get_settings", return_value=auth_settings),
        patch("api.services.pack_sync_service.get_settings", return_value=pack_sync_settings),
    ):
        denied = client.get("/api/v1/cook/packs")
        assert denied.status_code == 401
        assert denied.json() == {"detail": "Invalid pack sync token"}

        ok = client.get(
            "/api/v1/cook/packs",
            headers={"X-Pack-Sync-Token": "token123"},
        )
        assert ok.status_code == 200

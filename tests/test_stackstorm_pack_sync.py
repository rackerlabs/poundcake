import io
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api.cook import router as cook_router
from api.api.internal_stackstorm import router as internal_stackstorm_router
from api.core.database import get_db
from api.services.stackstorm_service import build_stackstorm_pack_artifact


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


def test_pack_artifact_endpoint_requires_token_and_supports_etag():
    app = FastAPI()
    app.include_router(cook_router, prefix="/api/v1")
    app.include_router(internal_stackstorm_router, prefix="/api/v1")

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

    with (
        patch("api.services.pack_sync_service.get_settings", return_value=settings),
        patch("api.api.internal_stackstorm.record_deprecated_endpoint_hit") as deprecated_metric,
    ):
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

        alias = client.get(
            "/api/v1/internal/stackstorm/pack.tgz",
            headers={"X-Pack-Sync-Token": "token123"},
        )
        assert alias.status_code == 200
        deprecated_metric.assert_called_once()

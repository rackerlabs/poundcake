from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from api.main import app as poundcake_app
from bakery.main import app as bakery_app
from contracts.communications import (
    CommunicationAcceptedResponse,
    CommunicationCreateRequest,
    CommunicationNotifyRequest,
)
from contracts.generate_artifacts import build_model_schemas, build_openapi


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs" / "contracts"
ROUTE_EXCLUSIONS = {"/api/v1/cook/packs"}


def _json_api_routes(app) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v1")
        and route.path not in ROUTE_EXCLUSIONS
    ]


@pytest.mark.parametrize("route", _json_api_routes(poundcake_app), ids=lambda route: route.path)
def test_poundcake_api_routes_declare_response_models(route: APIRoute) -> None:
    assert route.response_model is not None, f"{route.path} is missing response_model"


@pytest.mark.parametrize("route", _json_api_routes(bakery_app), ids=lambda route: route.path)
def test_bakery_api_routes_declare_response_models(route: APIRoute) -> None:
    assert route.response_model is not None, f"{route.path} is missing response_model"


def test_shared_contract_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CommunicationCreateRequest.model_validate(
            {
                "title": "Disk alert",
                "description": "details",
                "unexpected": "boom",
            }
        )

    with pytest.raises(ValidationError):
        CommunicationNotifyRequest.model_validate({"comment": "legacy alias"})


def test_shared_contract_accepted_response_requires_canonical_field_names() -> None:
    with pytest.raises(ValidationError):
        CommunicationAcceptedResponse.model_validate(
            {
                "ticket_id": "legacy-id",
                "operation_id": "op-1",
                "action": "create",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00Z",
            }
        )


def test_generated_contract_artifacts_match_repo_snapshots() -> None:
    shared_models_path = DOCS_DIR / "shared-models.json"
    assert shared_models_path.exists()
    assert json.loads(shared_models_path.read_text(encoding="utf-8")) == build_model_schemas()

    for artifact_name, payload in build_openapi().items():
        path = DOCS_DIR / artifact_name
        assert path.exists(), f"missing generated artifact {artifact_name}"
        assert json.loads(path.read_text(encoding="utf-8")) == payload

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.schemas.schemas import (
    AlertmanagerWebhookRequest,
    IngredientCreate,
    PrometheusRuleWriteRequest,
    SettingsResponse,
)
from api.services.repo_sync_service import RepoWorkflowDocument
from bakery.schemas import TicketCreateRequest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_owned_api_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IngredientCreate.model_validate(
            {
                "execution_target": "core.local",
                "task_key_template": "core.local",
                "expected_duration_sec": 30,
                "unexpected": "boom",
            }
        )


def test_settings_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SettingsResponse.model_validate(
            {
                "auth_enabled": True,
                "rbac_enabled": True,
                "auth_providers": [],
                "prometheus_use_crds": True,
                "prometheus_crd_namespace": "rackspace",
                "prometheus_url": "https://prom.example",
                "git_enabled": False,
                "git_provider": None,
                "git_repo_url": None,
                "git_branch": None,
                "git_rules_path": None,
                "git_workflows_path": None,
                "git_actions_path": None,
                "stackstorm_enabled": True,
                "version": "2.0.0",
                "global_communications_configured": False,
                "unexpected": "boom",
            }
        )


def test_prometheus_rule_write_request_accepts_query_alias() -> None:
    payload = PrometheusRuleWriteRequest.model_validate(
        {
            "alert": "DiskFull",
            "query": "node_filesystem_avail_bytes == 0",
            "for": "5m",
        }
    )

    assert payload.expr == "node_filesystem_avail_bytes == 0"
    assert payload.for_ == "5m"


def test_alertmanager_webhook_request_still_allows_extra_fields() -> None:
    payload = AlertmanagerWebhookRequest.model_validate(
        {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "fp-1",
                    "startsAt": "2026-03-23T12:00:00Z",
                    "labels": {
                        "alertname": "DiskFull",
                        "group_name": "filesystem-response",
                        "severity": "warning",
                        "instance": "host1",
                    },
                    "annotations": {
                        "summary": "Filesystem almost full",
                        "description": "Usage exceeded the alert threshold.",
                        "runbook_url": "https://docs.example.com/runbooks/filesystem",
                    },
                    "generatorURL": "https://prometheus.example/graph",
                    "extra_field": "allowed",
                }
            ],
            "externalURL": "https://alertmanager.example",
        }
    )

    assert payload.status == "firing"
    assert payload.alerts[0].labels["alertname"] == "DiskFull"


def test_bakery_ticket_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TicketCreateRequest.model_validate(
            {
                "title": "Disk alert",
                "description": "details",
                "unexpected": "boom",
            }
        )


def test_repo_sync_document_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RepoWorkflowDocument.model_validate(
            {
                "name": "sync-doc",
                "enabled": True,
                "communications": {"mode": "inherit", "routes": []},
                "recipe_ingredients": [],
                "unexpected": "boom",
            }
        )


def test_public_json_routes_define_response_models() -> None:
    exempt_paths = {
        "/auth/oidc/login",
        "/auth/oidc/callback",
        "/cook/packs",
    }
    missing: list[str] = []

    for relative_dir in ("api/api", "bakery/api"):
        for path in sorted((REPO_ROOT / relative_dir).glob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(module):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    if not isinstance(decorator.func, ast.Attribute):
                        continue
                    if decorator.func.attr not in {"get", "post", "put", "patch", "delete"}:
                        continue
                    if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                        continue
                    route_path = decorator.args[0].value
                    if not isinstance(route_path, str):
                        continue
                    if route_path in exempt_paths:
                        continue
                    has_response_model = any(
                        keyword.arg == "response_model" for keyword in decorator.keywords
                    )
                    if not has_response_model:
                        missing.append(f"{decorator.func.attr.upper()} {relative_dir}/{path.name}:{route_path}")

    assert missing == []

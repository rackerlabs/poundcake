from __future__ import annotations

import pytest

from api.schemas.schemas import SettingsResponse
from cli.client import PoundCakeClient, PoundCakeClientError


def _client() -> PoundCakeClient:
    return PoundCakeClient("https://poundcake.example", api_key="token")


def test_cli_get_settings_rejects_unexpected_response_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
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
        },
    )

    with pytest.raises(PoundCakeClientError):
        client.get_settings()


def test_cli_get_settings_returns_typed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
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
        },
    )

    payload = client.get_settings()

    assert isinstance(payload, SettingsResponse)


def test_cli_create_ingredient_validates_request_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    called = {"value": False}

    def _fake_request(*args, **kwargs):
        called["value"] = True
        return {}

    monkeypatch.setattr(client, "_request", _fake_request)

    with pytest.raises(PoundCakeClientError):
        client.create_ingredient({"execution_target": "discord"})

    assert called["value"] is False


def test_cli_list_rules_rejects_unexpected_rule_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "rules": [
                {
                    "group": "filesystem",
                    "name": "DiskFull",
                    "query": "node_filesystem_avail_bytes == 0",
                    "unexpected": "boom",
                }
            ],
            "source": "crds",
        },
    )

    with pytest.raises(PoundCakeClientError):
        client.list_rules()


def test_cli_get_rule_matches_canonicalized_crd_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "rules": [
                {
                    "group": "MixedCaseGroup",
                    "crd": "mixed-case-source",
                    "name": "DiskFull",
                    "query": "node_filesystem_avail_bytes == 0",
                    "duration": "5m",
                    "labels": {"severity": "warning"},
                    "annotations": {"summary": "Disk filling up"},
                    "state": "unknown",
                    "health": "unknown",
                }
            ],
            "source": "crds",
        },
    )

    payload = client.get_rule("Mixed Case Source.yaml", "MixedCaseGroup", "DiskFull")

    assert payload.crd == "mixed-case-source"
    assert payload.name == "DiskFull"


def test_cli_list_orders_rejects_unexpected_order_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: [
            {
                "id": 7,
                "req_id": "req-1",
                "fingerprint": "fp-1",
                "alert_status": "firing",
                "alert_group_name": "Disk Full",
                "labels": {"alertname": "DiskFull"},
                "starts_at": "2026-01-01T00:00:00+00:00",
                "processing_status": "processing",
                "is_active": True,
                "counter": 1,
                "communications": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:05:00+00:00",
                "unexpected": "boom",
            }
        ],
    )

    with pytest.raises(PoundCakeClientError):
        client.list_orders()


def test_cli_observability_overview_rejects_invalid_nested_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "health": {},
            "queue": {"orders_new": 1, "orders_processing": 2},
            "failures": {
                "orders_failed": 0,
                "dishes_failed": 0,
                "top_errors": [],
                "runbook_hints": [],
            },
            "bakery": {"summary_failures": 0, "order_dead_letters": 0},
            "suppressions": {"active": 1, "retrying_operations": 0, "dead_letter": 0},
        },
    )

    with pytest.raises(PoundCakeClientError):
        client.observability_overview()


def test_cli_list_auth_bindings_rejects_unexpected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: [
            {
                "id": 17,
                "provider": "auth0",
                "binding_type": "group",
                "role": "operator",
                "external_group": "monitoring-operators",
                "created_by": "alice",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "principal": None,
                "unexpected": "boom",
            }
        ],
    )

    with pytest.raises(PoundCakeClientError):
        client.list_auth_bindings()


def test_cli_list_communications_rejects_unexpected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: [
            {
                "communication_id": "comm-1",
                "reference_type": "incident",
                "reference_id": "7",
                "channel": "rackspace_core",
                "unexpected": "boom",
            }
        ],
    )

    with pytest.raises(PoundCakeClientError):
        client.list_communications()

from __future__ import annotations

import pytest

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

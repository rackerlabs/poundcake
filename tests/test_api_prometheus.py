from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.api.prometheus import create_rule, delete_rule, list_rules, update_rule
from api.services.alert_rule_repo import (
    AlertRuleSource,
    dump_alert_rule_sources_to_annotations,
)
from api.schemas.schemas import PrometheusRuleWriteRequest


def _request(method: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(req_id="req-1"), method=method)


@pytest.mark.asyncio
async def test_create_rule_preserves_http_400_from_rule_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create_rule(**kwargs):
        return {
            "status": "error",
            "message": "bad rule payload",
        }

    monkeypatch.setattr(
        "api.api.prometheus.get_prometheus_rule_manager",
        lambda: SimpleNamespace(create_rule=_create_rule),
    )

    with pytest.raises(HTTPException) as excinfo:
        await create_rule(
            request=_request("POST"),
            rule_name="DiskFull",
            group_name="node",
            file_name="rules-file",
            payload=PrometheusRuleWriteRequest(alert="DiskFull", expr="up == 0"),
            _user=None,
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "bad rule payload"


@pytest.mark.asyncio
async def test_update_rule_preserves_http_400_from_rule_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _update_rule(**kwargs):
        return {
            "status": "error",
            "message": "bad update payload",
        }

    monkeypatch.setattr(
        "api.api.prometheus.get_prometheus_rule_manager",
        lambda: SimpleNamespace(update_rule=_update_rule),
    )

    with pytest.raises(HTTPException) as excinfo:
        await update_rule(
            rule_name="DiskFull",
            request=_request("PUT"),
            group_name="node",
            file_name="rules-file",
            payload=PrometheusRuleWriteRequest(alert="DiskFull", expr="up == 1"),
            _user=None,
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "bad update payload"


@pytest.mark.asyncio
async def test_delete_rule_preserves_http_400_from_rule_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _delete_rule(**kwargs):
        return {
            "status": "error",
            "message": "rule not found",
        }

    monkeypatch.setattr(
        "api.api.prometheus.get_prometheus_rule_manager",
        lambda: SimpleNamespace(delete_rule=_delete_rule),
    )

    with pytest.raises(HTTPException) as excinfo:
        await delete_rule(
            request=_request("DELETE"),
            rule_name="DiskFull",
            group_name="node",
            file_name="rules-file",
            _user=None,
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "rule not found"


@pytest.mark.asyncio
async def test_list_rules_surfaces_repo_relative_file_from_crd_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = dump_alert_rule_sources_to_annotations(
        {},
        {
            "kube-api-down-warning": AlertRuleSource(
                relative_path="kubernetes/kube-api-down.yaml",
                source_format="additionalPrometheusRulesMap",
                wrapper_key="kube-api-down",
            )
        },
    )

    async def _get_rules():
        return [
            {
                "metadata": {
                    "name": "kube-api-down",
                    "namespace": "poundcake",
                    "annotations": annotations,
                },
                "spec": {
                    "groups": [
                        {
                            "name": "kube-api-down",
                            "rules": [
                                {
                                    "alert": "kube-api-down-warning",
                                    "expr": "up == 0",
                                    "for": "5m",
                                    "labels": {"severity": "warning"},
                                    "annotations": {"summary": "Kube API is down"},
                                }
                            ],
                        }
                    ]
                },
            }
        ]

    monkeypatch.setattr(
        "api.api.prometheus.get_settings",
        lambda: SimpleNamespace(prometheus_use_crds=True),
    )
    monkeypatch.setattr(
        "api.api.prometheus.PrometheusCRDManager",
        lambda: SimpleNamespace(get_prometheus_rules=_get_rules),
    )

    response = await list_rules(request=_request("GET"), _user=None)

    assert response.source == "crds"
    assert response.rules[0].crd == "kube-api-down"
    assert response.rules[0].file == "kubernetes/kube-api-down.yaml"

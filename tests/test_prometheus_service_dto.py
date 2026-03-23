from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.prometheus_service import PrometheusClient


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_prometheus_client_get_rules_normalizes_owned_rule_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.prometheus_service.get_settings",
        lambda: SimpleNamespace(
            prometheus_url="https://prom.example",
            prometheus_verify_ssl=False,
            external_http_retries=1,
        ),
    )
    client = PrometheusClient()

    async def _request(*args, **kwargs):
        return _Resp(
            200,
            {
                "status": "success",
                "data": {
                    "groups": [
                        {
                            "name": "node",
                            "file": None,
                            "interval": 30,
                            "rules": [
                                {
                                    "name": "DiskFull",
                                    "query": "up == 0",
                                    "duration": "",
                                    "labels": {"severity": "critical"},
                                    "annotations": {"summary": "Disk full"},
                                    "state": "inactive",
                                    "health": "ok",
                                    "type": "alerting",
                                    "alerts": [{"labels": {"alertname": "DiskFull"}}],
                                }
                            ],
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(client, "_request", _request)

    payload = await client.get_rules()

    assert payload == [
        {
            "group": "node",
            "file": None,
            "interval": "30",
            "name": "DiskFull",
            "query": "up == 0",
            "duration": None,
            "labels": {"severity": "critical"},
            "annotations": {"summary": "Disk full"},
            "state": "inactive",
            "health": "ok",
        }
    ]

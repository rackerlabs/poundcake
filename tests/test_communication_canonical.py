from __future__ import annotations

from datetime import datetime, timezone

from api.models.models import Order
from api.services.communication_canonical import build_canonical_communication_context


def test_build_canonical_communication_context_includes_alert_links_and_route_config() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=7,
        req_id="REQ-7",
        fingerprint="fp-7",
        alert_status="firing",
        processing_status="processing",
        is_active=True,
        remediation_outcome="failed",
        clear_timeout_sec=300,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="filesystem-response",
        severity="warning",
        instance="host7",
        counter=2,
        labels={"alertname": "DiskFull", "group_name": "filesystem-response", "severity": "warning", "instance": "host7"},
        annotations={
            "summary": "Filesystem almost full",
            "description": "Usage exceeded the alert threshold.",
            "runbook_url": "https://docs.example.com/runbooks/filesystem",
            "dashboard_url": "https://grafana.example/d/fs",
        },
        raw_data={"generatorURL": "https://prometheus.example/graph?g0.expr=disk"},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )

    payload = {
        "title": "Alert requires attention",
        "description": "PoundCake escalated this alert.",
        "message": "Automated remediation failed.",
        "context": {
            "route_label": "Primary Core",
            "provider_config": {"account_number": "1781738", "queue": "CloudBuilders Support"},
            "semantic_text": {
                "headline": "Alert requires attention",
                "summary": "PoundCake escalated this alert.",
                "detail": "Automated remediation failed.",
                "resolution": "",
            },
            "poundcake_policy": {
                "managed": True,
                "event": "escalation_open",
                "route_id": "core-primary",
                "label": "Primary Core",
            },
        },
    }

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="open",
        execution_payload=payload,
    )

    assert canonical["route"]["provider_config"]["account_number"] == "1781738"
    assert canonical["alert"]["annotations"]["summary"] == "Filesystem almost full"
    assert canonical["text"]["detail"] == "Automated remediation failed."
    assert canonical["links"][0]["label"] == "Source"
    assert canonical["links"][1]["label"] == "Runbook"

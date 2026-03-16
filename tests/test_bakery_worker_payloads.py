from __future__ import annotations

import sys
import types

if "structlog" not in sys.modules:
    structlog_stub = types.ModuleType("structlog")
    setattr(
        structlog_stub,
        "get_logger",
        lambda *args, **kwargs: types.SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )
    sys.modules["structlog"] = structlog_stub

from bakery.models import Ticket
from bakery.worker import _build_provider_payload


def _canonical_payload() -> dict:
    return {
        "comment": "legacy comment should not win",
        "resolution_notes": "legacy close note should not win",
        "context": {
            "_canonical": {
                "schema_version": 1,
                "event": {
                    "name": "resolved_success_close",
                    "operation": "close",
                    "managed": True,
                    "source": "poundcake",
                },
                "route": {
                    "label": "Primary route",
                    "execution_target": "rackspace_core",
                    "destination_target": "primary",
                    "provider_config": {"visibility": "internal"},
                },
                "order": {
                    "id": 7,
                    "req_id": "REQ-7",
                    "remediation_outcome": "succeeded",
                },
                "alert": {
                    "group_name": "filesystem-response",
                    "severity": "warning",
                    "status": "resolved",
                    "fingerprint": "fp-7",
                    "instance": "host7",
                    "starts_at": "2026-03-13T12:00:00Z",
                    "ends_at": "2026-03-13T12:05:00Z",
                    "labels": {"alertname": "DiskFull"},
                    "annotations": {
                        "summary": "Filesystem almost full",
                        "description": "Usage exceeded the alert threshold.",
                    },
                    "generator_url": "https://prometheus.example/graph?g0.expr=disk",
                },
                "links": [
                    {"label": "Source", "url": "https://prometheus.example/graph?g0.expr=disk"},
                ],
                "text": {
                    "headline": "Alert resolved",
                    "summary": "PoundCake remediated this alert successfully.",
                    "detail": "Filesystem recovered after cleanup.",
                    "resolution": "Closing communication after successful remediation.",
                },
                "remediation": {
                    "summary": {
                        "total": 2,
                        "succeeded": 2,
                        "failed": 0,
                        "skipped": 0,
                        "incomplete": 0,
                    },
                    "steps": [
                        {
                            "task_key": "step_1_cleanup_var",
                            "status": "succeeded",
                            "outcome": "Freed 12 GB on /var",
                        },
                        {
                            "task_key": "step_2_verify_var",
                            "status": "succeeded",
                            "outcome": "Confirmed disk recovery on /var",
                        },
                    ],
                    "before_excerpt": "stdout:\nDisk usage before cleanup was 95% on /var",
                    "after_excerpt": "stdout:\nDisk usage after cleanup was 40% on /var",
                    "failure_excerpt": "",
                    "latest_completed_step": {
                        "task_key": "step_2_verify_var",
                        "status": "succeeded",
                        "outcome": "Confirmed disk recovery on /var",
                    },
                },
            }
        },
    }


def test_build_provider_payload_rackspace_core_close_uses_rendered_remediation_close_notes() -> (
    None
):
    ticket = Ticket(
        internal_ticket_id="comm-1",
        provider_type="rackspace_core",
        provider_ticket_id="260101-00001",
        state="open",
    )

    rendered = _build_provider_payload("close", ticket, _canonical_payload())

    assert rendered["ticket_id"] == "260101-00001"
    assert "Closing communication after successful remediation." in rendered["close_notes"]
    assert "Before remediation excerpt" in rendered["close_notes"]
    assert "After remediation excerpt" in rendered["close_notes"]
    assert rendered["close_notes"] != "legacy close note should not win"


def test_build_provider_payload_discord_comment_uses_compact_rendered_payload() -> None:
    ticket = Ticket(
        internal_ticket_id="comm-2",
        provider_type="discord",
        provider_ticket_id=None,
        state="open",
    )
    payload = _canonical_payload()
    payload["context"]["_canonical"]["event"]["operation"] = "comment"
    payload["context"]["_canonical"]["event"]["name"] = "resolved_failure_notify"
    payload["context"]["_canonical"]["order"]["remediation_outcome"] = "failed"
    payload["context"]["_canonical"]["remediation"]["summary"]["succeeded"] = 1
    payload["context"]["_canonical"]["remediation"]["summary"]["failed"] = 1
    payload["context"]["_canonical"]["remediation"]["after_excerpt"] = ""
    payload["context"]["_canonical"]["remediation"][
        "failure_excerpt"
    ] = "Authorization: Bearer secret-token\nstderr:\nPermission denied while validating"
    payload["context"]["_canonical"]["remediation"]["steps"][1]["status"] = "failed"
    payload["context"]["_canonical"]["remediation"]["steps"][1][
        "outcome"
    ] = "Permission denied while validating"

    rendered = _build_provider_payload("comment", ticket, payload)

    assert rendered["ticket_id"] == "comm-2"
    assert rendered["message"] == "Alert resolved"
    field_names = [field["name"] for field in rendered["embeds"][0]["fields"]]
    assert "Remediation" in field_names
    assert "Failure excerpt" in field_names
    assert "secret-token" not in rendered["embeds"][0]["fields"][-1]["value"]

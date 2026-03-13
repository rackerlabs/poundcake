from __future__ import annotations

from copy import deepcopy

from bakery.formatters import provider_config_from_context, render_provider_content


def _canonical_payload() -> dict:
    return {
        "context": {
            "_canonical": {
                "schema_version": 1,
                "event": {
                    "name": "escalation_open",
                    "operation": "open",
                    "managed": True,
                    "source": "poundcake",
                },
                "route": {
                    "label": "Primary route",
                    "execution_target": "rackspace_core",
                    "destination_target": "primary",
                    "provider_config": {},
                },
                "order": {"id": 7, "req_id": "REQ-7"},
                "alert": {
                    "group_name": "filesystem-response",
                    "severity": "warning",
                    "status": "firing",
                    "fingerprint": "fp-7",
                    "instance": "host7",
                    "starts_at": "2026-03-13T12:00:00Z",
                    "ends_at": None,
                    "labels": {"alertname": "DiskFull"},
                    "annotations": {
                        "summary": "Filesystem almost full",
                        "description": "Usage exceeded the alert threshold.",
                    },
                    "generator_url": "https://prometheus.example/graph?g0.expr=disk",
                },
                "links": [
                    {"label": "Source", "url": "https://prometheus.example/graph?g0.expr=disk"},
                    {"label": "Runbook", "url": "https://docs.example.com/runbooks/filesystem"},
                ],
                "text": {
                    "headline": "Alert requires attention",
                    "summary": "PoundCake escalated this alert.",
                    "detail": "Automated remediation failed. See https://docs.example.com/runbooks/filesystem",
                    "resolution": "",
                },
                "remediation": {
                    "summary": {
                        "total": 2,
                        "succeeded": 1,
                        "failed": 1,
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
                            "status": "failed",
                            "outcome": "Permission denied while validating free space",
                        },
                    ],
                    "before_excerpt": "stdout:\nDisk usage before cleanup was 95% on /var",
                    "after_excerpt": "",
                    "failure_excerpt": (
                        "Authorization: Bearer secret-token\n\n"
                        "stderr:\nPermission denied while validating free space"
                    ),
                    "latest_completed_step": {
                        "task_key": "step_1_cleanup_var",
                        "status": "succeeded",
                        "outcome": "Freed 12 GB on /var",
                    },
                },
            }
        }
    }


def test_render_provider_content_rackspace_core_uses_bbcode_links() -> None:
    rendered = render_provider_content("rackspace_core", "create", _canonical_payload())

    assert rendered["subject"].startswith("Alert requires attention")
    assert "[url=https://prometheus.example/graph?g0.expr=disk]" in rendered["body"]
    assert "[b]Remediation[/b]" in rendered["body"]
    assert "[b]Failure excerpt[/b]" in rendered["body"]
    assert "secret-token" not in rendered["body"]
    assert "[REDACTED]" in rendered["body"]
    assert rendered["severity"] == "warning"


def test_render_provider_content_jira_returns_adf_comment() -> None:
    rendered = render_provider_content("jira", "comment", _canonical_payload())

    assert rendered["comment"]["type"] == "doc"
    assert rendered["comment"]["version"] == 1


def test_render_provider_content_github_returns_markdown_links() -> None:
    rendered = render_provider_content("github", "comment", _canonical_payload())

    assert "## Alert requires attention" in rendered["comment"]
    assert "[Runbook](https://docs.example.com/runbooks/filesystem)" in rendered["comment"]
    assert "**Remediation**" in rendered["comment"]
    assert "Latest completed step:" in rendered["comment"]
    assert "```text" in rendered["comment"]


def test_render_provider_content_discord_returns_embed_payload() -> None:
    rendered = render_provider_content("discord", "create", _canonical_payload())

    assert rendered["message"] == "Alert requires attention"
    assert rendered["embeds"][0]["title"]
    assert rendered["embeds"][0]["color"] == 0xF79009
    field_names = [field["name"] for field in rendered["embeds"][0]["fields"]]
    assert "Remediation" in field_names
    assert "Failure excerpt" in field_names
    assert "secret-token" not in rendered["embeds"][0]["fields"][-1]["value"]
    assert "[REDACTED]" in rendered["embeds"][0]["fields"][-1]["value"]


def test_render_provider_content_discord_resolved_messages_use_green_embed() -> None:
    payload = deepcopy(_canonical_payload())
    payload["context"]["_canonical"]["event"]["name"] = "resolved_success_close"
    payload["context"]["_canonical"]["event"]["operation"] = "close"
    payload["context"]["_canonical"]["order"]["remediation_outcome"] = "succeeded"
    payload["context"]["_canonical"]["alert"]["severity"] = "critical"
    payload["context"]["_canonical"]["alert"]["status"] = "resolved"
    payload["context"]["_canonical"]["alert"]["ends_at"] = "2026-03-13T12:03:00Z"
    payload["context"]["_canonical"]["text"]["headline"] = "Alert resolved"
    payload["context"]["_canonical"]["text"]["resolution"] = "Closing communication after recovery."
    payload["context"]["_canonical"]["remediation"]["summary"]["failed"] = 0
    payload["context"]["_canonical"]["remediation"]["summary"]["succeeded"] = 2
    payload["context"]["_canonical"]["remediation"][
        "after_excerpt"
    ] = "stdout:\nDisk usage after cleanup was 40% on /var"
    payload["context"]["_canonical"]["remediation"]["failure_excerpt"] = ""
    payload["context"]["_canonical"]["remediation"]["steps"][1]["status"] = "succeeded"
    payload["context"]["_canonical"]["remediation"]["steps"][1][
        "outcome"
    ] = "Confirmed disk recovery on /var"
    payload["context"]["_canonical"]["remediation"]["latest_completed_step"] = {
        "task_key": "step_2_verify_var",
        "status": "succeeded",
        "outcome": "Confirmed disk recovery on /var",
    }

    rendered = render_provider_content("discord", "close", payload)

    assert rendered["embeds"][0]["color"] == 0x12B76A
    field_names = [field["name"] for field in rendered["embeds"][0]["fields"]]
    assert "After remediation excerpt" in field_names


def test_render_provider_content_servicenow_close_includes_before_and_after_excerpts() -> None:
    payload = deepcopy(_canonical_payload())
    payload["context"]["_canonical"]["event"]["name"] = "resolved_success_close"
    payload["context"]["_canonical"]["event"]["operation"] = "close"
    payload["context"]["_canonical"]["order"]["remediation_outcome"] = "succeeded"
    payload["context"]["_canonical"]["text"]["resolution"] = "Closing communication after recovery."
    payload["context"]["_canonical"]["remediation"]["summary"]["failed"] = 0
    payload["context"]["_canonical"]["remediation"]["summary"]["succeeded"] = 2
    payload["context"]["_canonical"]["remediation"][
        "after_excerpt"
    ] = "stdout:\nDisk usage after cleanup was 40% on /var"
    payload["context"]["_canonical"]["remediation"]["failure_excerpt"] = ""
    payload["context"]["_canonical"]["remediation"]["steps"][1]["status"] = "succeeded"
    payload["context"]["_canonical"]["remediation"]["steps"][1][
        "outcome"
    ] = "Confirmed disk recovery on /var"

    rendered = render_provider_content("servicenow", "close", payload)

    assert "Remediation" in rendered["close_notes"]
    assert "Before remediation excerpt" in rendered["close_notes"]
    assert "After remediation excerpt" in rendered["close_notes"]


def test_provider_config_from_context_prefers_route_provider_config() -> None:
    payload = {
        "context": {
            "provider_config": {"owner": "rackerlabs", "repo": "poundcake"},
            "githubOwner": "legacy-owner",
            "githubRepo": "legacy-repo",
        }
    }

    config = provider_config_from_context("github", payload)

    assert config["owner"] == "rackerlabs"
    assert config["repo"] == "poundcake"

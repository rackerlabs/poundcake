from __future__ import annotations

from bakery.formatters import provider_config_from_context, render_provider_content


def _canonical_payload() -> dict:
    return {
        "context": {
            "_canonical": {
                "schema_version": 1,
                "event": {"name": "escalation_open", "operation": "open", "managed": True, "source": "poundcake"},
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
            }
        }
    }


def test_render_provider_content_rackspace_core_uses_bbcode_links() -> None:
    rendered = render_provider_content("rackspace_core", "create", _canonical_payload())

    assert rendered["subject"].startswith("Alert requires attention")
    assert "[url=https://prometheus.example/graph?g0.expr=disk]" in rendered["body"]
    assert rendered["severity"] == "warning"


def test_render_provider_content_jira_returns_adf_comment() -> None:
    rendered = render_provider_content("jira", "comment", _canonical_payload())

    assert rendered["comment"]["type"] == "doc"
    assert rendered["comment"]["version"] == 1


def test_render_provider_content_github_returns_markdown_links() -> None:
    rendered = render_provider_content("github", "comment", _canonical_payload())

    assert "## Alert requires attention" in rendered["comment"]
    assert "[Runbook](https://docs.example.com/runbooks/filesystem)" in rendered["comment"]


def test_render_provider_content_discord_returns_embed_payload() -> None:
    rendered = render_provider_content("discord", "create", _canonical_payload())

    assert rendered["message"] == "Alert requires attention"
    assert rendered["embeds"][0]["title"]


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

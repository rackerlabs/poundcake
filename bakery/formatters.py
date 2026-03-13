#!/usr/bin/env python3
"""Provider-native communication renderers for Bakery."""

from __future__ import annotations

import re
from typing import Any

URL_RE = re.compile(r"(https?://[^\s<>\]]+)")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _csv_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [_text(value)] if _text(value) else []


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _auto_link_bbcode(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        url = match.group(1)
        return f"[url={url}]{url}[/url]"

    return URL_RE.sub(_replace, text)


def _auto_link_markdown(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        url = match.group(1)
        return f"[{url}]({url})"

    return URL_RE.sub(_replace, text)


def _dedupe_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for link in links:
        label = _text(link.get("label"))
        url = _text(link.get("url"))
        if not url:
            continue
        key = (label.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        unique.append({"label": label or url, "url": url})
    return unique


def _split_text_with_urls(text: str) -> list[tuple[str, bool]]:
    if not text:
        return []
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for match in URL_RE.finditer(text):
        start, end = match.span()
        if start > cursor:
            parts.append((text[cursor:start], False))
        parts.append((match.group(1), True))
        cursor = end
    if cursor < len(text):
        parts.append((text[cursor:], False))
    return [(segment, is_url) for segment, is_url in parts if segment]


def _build_fallback_canonical(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    labels = context.get("labels") if isinstance(context.get("labels"), dict) else {}
    annotations = context.get("annotations") if isinstance(context.get("annotations"), dict) else {}
    route_label = _text(context.get("route_label"))
    links: list[dict[str, str]] = []
    generator_url = _text(context.get("generatorURL") or payload.get("generatorURL"))
    if generator_url:
        links.append({"label": "Source", "url": generator_url})
    for key, label in (
        ("runbook_url", "Runbook"),
        ("dashboard_url", "Dashboard"),
        ("playbook_url", "Playbook"),
        ("investigation_url", "Investigation"),
        ("silence_url", "Silence"),
    ):
        url = _text(annotations.get(key) or context.get(key) or payload.get(key))
        if url:
            links.append({"label": label, "url": url})

    return {
        "schema_version": 1,
        "event": {
            "name": _text(context.get("event_name")),
            "operation": action,
            "managed": False,
            "source": _text(payload.get("source") or context.get("source") or "poundcake"),
        },
        "route": {
            "id": _text(context.get("route_id")),
            "label": route_label,
            "execution_target": _text(context.get("provider_type")),
            "destination_target": _text(context.get("destination_target")),
            "provider_config": (
                context.get("provider_config")
                if isinstance(context.get("provider_config"), dict)
                else {}
            ),
        },
        "order": {
            "id": context.get("order_id"),
            "req_id": _text(context.get("req_id")),
            "processing_status": _text(context.get("processing_status")),
            "alert_status": _text(context.get("alert_status")),
            "remediation_outcome": _text(context.get("remediation_outcome")),
            "counter": context.get("counter"),
            "clear_timeout_sec": context.get("clear_timeout_sec"),
            "clear_deadline_at": _text(context.get("clear_deadline_at")),
            "clear_timed_out_at": _text(context.get("clear_timed_out_at")),
            "auto_close_eligible": bool(context.get("auto_close_eligible", False)),
        },
        "alert": {
            "group_name": _text(labels.get("group_name") or labels.get("alertname")),
            "severity": _text(payload.get("severity") or labels.get("severity") or "unknown"),
            "status": _text(context.get("alert_status")),
            "fingerprint": _text(context.get("fingerprint")),
            "instance": _text(labels.get("instance")),
            "starts_at": _text(context.get("starts_at")),
            "ends_at": _text(context.get("ends_at")),
            "labels": labels,
            "annotations": annotations,
            "generator_url": generator_url,
        },
        "links": _dedupe_links(links),
        "text": {
            "headline": _text(
                payload.get("title") or payload.get("message") or payload.get("comment")
            ),
            "summary": _text(payload.get("description") or annotations.get("summary")),
            "detail": _text(
                payload.get("message")
                or payload.get("comment")
                or payload.get("resolution_notes")
                or annotations.get("description")
            ),
            "resolution": _text(payload.get("resolution_notes") or payload.get("comment")),
        },
    }


def canonical_from_payload(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    canonical = context.get("_canonical")
    if isinstance(canonical, dict):
        return canonical
    return _build_fallback_canonical(action, payload)


def provider_config_from_context(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    provider_config = (
        dict(context.get("provider_config"))
        if isinstance(context.get("provider_config"), dict)
        else {}
    )
    legacy_context = {
        "rackspace_core": (
            (
                "account_number",
                context.get("account_number")
                or context.get("accountNumber")
                or context.get("coreAccountID")
                or context.get("rackspace_com_coreAccountID"),
            ),
            ("queue", context.get("queue") or context.get("coreQueue")),
            ("subcategory", context.get("subcategory") or context.get("coreSubcategory")),
            ("source", context.get("source")),
            ("visibility", context.get("visibility")),
        ),
        "servicenow": (
            ("urgency", context.get("urgency") or context.get("serviceNowUrgency")),
            ("impact", context.get("impact") or context.get("serviceNowImpact")),
        ),
        "jira": (
            ("project_key", context.get("project_key") or context.get("jiraProjectKey")),
            ("issue_type", context.get("issue_type") or context.get("jiraIssueType")),
            ("transition_id", context.get("transition_id")),
        ),
        "github": (
            ("owner", context.get("owner") or context.get("githubOwner")),
            ("repo", context.get("repo") or context.get("githubRepo")),
            ("labels", context.get("labels") or context.get("githubLabels")),
            ("assignees", context.get("assignees") or context.get("githubAssignees")),
        ),
        "pagerduty": (
            ("service_id", context.get("service_id") or context.get("pagerDutyServiceId")),
            ("from_email", context.get("from_email") or context.get("pagerDutyFromEmail")),
            ("urgency", context.get("urgency") or context.get("pagerDutyUrgency")),
        ),
    }
    for key, value in legacy_context.get(provider, ()):
        if key in provider_config or value in (None, "", []):
            continue
        provider_config[key] = value
    if "labels" in provider_config:
        provider_config["labels"] = _csv_list(provider_config["labels"])
    if "assignees" in provider_config:
        provider_config["assignees"] = _csv_list(provider_config["assignees"])
    return provider_config


def _known_links(canonical: dict[str, Any]) -> list[dict[str, str]]:
    raw_links = canonical.get("links") if isinstance(canonical.get("links"), list) else []
    normalized = [
        {"label": _text(item.get("label")), "url": _text(item.get("url"))}
        for item in raw_links
        if isinstance(item, dict)
    ]
    return _dedupe_links(normalized)


def _title_from_canonical(canonical: dict[str, Any]) -> str:
    text = canonical.get("text") if isinstance(canonical.get("text"), dict) else {}
    alert = canonical.get("alert") if isinstance(canonical.get("alert"), dict) else {}
    headline = _text(text.get("headline"))
    summary = _text(
        alert.get("annotations", {}).get("summary")
        if isinstance(alert.get("annotations"), dict)
        else ""
    )
    base = summary or _text(alert.get("group_name")) or headline or "PoundCake communication"
    instance = _text(alert.get("instance"))
    if instance:
        base = f"{base} ({instance})"
    if headline and headline.lower() not in base.lower():
        base = f"{headline}: {base}"
    return _truncate(base, 255)


def _severity_color(severity: str) -> int:
    normalized = severity.lower()
    if normalized == "critical":
        return 0xD92D20
    if normalized in {"warning", "high"}:
        return 0xF79009
    if normalized in {"info", "low"}:
        return 0x2E90FA
    return 0x667085


def _discord_embed_color(model: dict[str, Any]) -> int:
    event_name = _text(model.get("event_name")).lower()
    alert_status = _text(model.get("alert_status")).lower()
    operation = _text(model.get("operation")).lower()
    remediation_outcome = _text(model.get("remediation_outcome")).lower()

    if operation == "close":
        return 0x12B76A
    if alert_status == "resolved":
        return 0x12B76A
    if event_name.startswith("resolved_") or event_name in {"fallback_notify", "alert_resolved"}:
        return 0x12B76A
    if remediation_outcome == "succeeded" and event_name.endswith("_close"):
        return 0x12B76A
    return _severity_color(model["severity"])


def _section_model(canonical: dict[str, Any], action: str) -> dict[str, Any]:
    text = canonical.get("text") if isinstance(canonical.get("text"), dict) else {}
    alert = canonical.get("alert") if isinstance(canonical.get("alert"), dict) else {}
    annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
    order = canonical.get("order") if isinstance(canonical.get("order"), dict) else {}
    event = canonical.get("event") if isinstance(canonical.get("event"), dict) else {}

    headline = _text(text.get("headline")) or _title_from_canonical(canonical)
    overview_lines: list[str] = []
    for line in (
        _text(text.get("summary")),
        _text(text.get("detail")),
        _text(annotations.get("summary")),
        _text(annotations.get("description")),
        _text(annotations.get("customer_impact")),
        _text(annotations.get("suggested_action")),
    ):
        if line and line not in overview_lines:
            overview_lines.append(line)
    if action == "close":
        resolution = _text(text.get("resolution"))
        if resolution:
            overview_lines.insert(0, resolution)

    links = _known_links(canonical)
    metadata = [
        ("Alert", _text(alert.get("group_name"))),
        ("Severity", _text(alert.get("severity"))),
        ("Status", _text(alert.get("status"))),
        ("Instance", _text(alert.get("instance"))),
        ("Fingerprint", _text(alert.get("fingerprint"))),
        ("Started", _text(alert.get("starts_at"))),
        ("Ended", _text(alert.get("ends_at"))),
        ("Order", _text(order.get("id"))),
        ("Request", _text(order.get("req_id"))),
    ]
    metadata = [(label, value) for label, value in metadata if value]
    return {
        "headline": headline,
        "title": _title_from_canonical(canonical),
        "overview": overview_lines,
        "links": links,
        "metadata": metadata,
        "severity": _text(alert.get("severity") or "unknown"),
        "alert_status": _text(alert.get("status")),
        "event_name": _text(event.get("name")),
        "operation": _text(event.get("operation") or action),
        "remediation_outcome": _text(order.get("remediation_outcome")),
    }


def _render_plain_sections(model: dict[str, Any]) -> str:
    parts = [model["headline"]]
    if model["overview"]:
        parts.append("")
        parts.append("Overview")
        parts.extend(model["overview"])
    if model["links"]:
        parts.append("")
        parts.append("Links")
        parts.extend(f"{item['label']}: {item['url']}" for item in model["links"])
    if model["metadata"]:
        parts.append("")
        parts.append("Metadata")
        parts.extend(f"{label}: {value}" for label, value in model["metadata"])
    return "\n".join(part for part in parts if part is not None).strip()


def _render_markdown_sections(model: dict[str, Any]) -> str:
    parts = [f"## {model['headline']}"]
    if model["overview"]:
        parts.append("")
        parts.append("**Overview**")
        parts.extend(_auto_link_markdown(line) for line in model["overview"])
    if model["links"]:
        parts.append("")
        parts.append("**Links**")
        parts.extend(f"- [{item['label']}]({item['url']})" for item in model["links"])
    if model["metadata"]:
        parts.append("")
        parts.append("**Metadata**")
        parts.extend(f"- **{label}**: {value}" for label, value in model["metadata"])
    return "\n".join(parts).strip()


def _render_bbcode_sections(model: dict[str, Any]) -> str:
    parts = [f"[b]{_auto_link_bbcode(model['headline'])}[/b]"]
    if model["overview"]:
        parts.append("")
        parts.append("[b]Overview[/b]")
        parts.extend(_auto_link_bbcode(line) for line in model["overview"])
    if model["links"]:
        parts.append("")
        parts.append("[b]Links[/b]")
        parts.extend(
            f"{item['label']}: [url={item['url']}]{item['url']}[/url]" for item in model["links"]
        )
    if model["metadata"]:
        parts.append("")
        parts.append("[b]Metadata[/b]")
        parts.extend(f"{label}: {_auto_link_bbcode(value)}" for label, value in model["metadata"])
    return "\n".join(parts).strip()


def _adf_text_nodes(text: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for segment, is_url in _split_text_with_urls(text):
        if is_url:
            nodes.append(
                {
                    "type": "text",
                    "text": segment,
                    "marks": [{"type": "link", "attrs": {"href": segment}}],
                }
            )
        else:
            nodes.append({"type": "text", "text": segment})
    return nodes or [{"type": "text", "text": text}]


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": _adf_text_nodes(text)}


def _render_adf_sections(model: dict[str, Any]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 2}, "content": _adf_text_nodes(model["headline"])}
    ]
    if model["overview"]:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes("Overview")}
        )
        content.extend(_adf_paragraph(line) for line in model["overview"])
    if model["links"]:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes("Links")}
        )
        content.append(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": f"{item['label']}: "},
                                    {
                                        "type": "text",
                                        "text": item["url"],
                                        "marks": [{"type": "link", "attrs": {"href": item["url"]}}],
                                    },
                                ],
                            }
                        ],
                    }
                    for item in model["links"]
                ],
            }
        )
    if model["metadata"]:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes("Metadata")}
        )
        content.append(
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_adf_paragraph(f"{label}: {value}")]}
                    for label, value in model["metadata"]
                ],
            }
        )
    return {"type": "doc", "version": 1, "content": content}


def _render_discord_message(model: dict[str, Any]) -> dict[str, Any]:
    content = _truncate(model["headline"], 1800)
    description_lines = model["overview"][:]
    if model["links"]:
        description_lines.append("")
        description_lines.extend(f"{item['label']}: {item['url']}" for item in model["links"])
    description = _truncate("\n".join(description_lines).strip(), 3500)
    fields = [
        {"name": label, "value": _truncate(value, 1000), "inline": True}
        for label, value in model["metadata"][:6]
    ]
    return {
        "message": content,
        "content": content,
        "embeds": [
            {
                "title": _truncate(model["title"], 256),
                "description": description or _truncate(model["headline"], 1024),
                "color": _discord_embed_color(model),
                "fields": fields,
            }
        ],
    }


def render_provider_content(provider: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_from_payload(action, payload)
    model = _section_model(canonical, action)
    source = _text(payload.get("source") or canonical.get("event", {}).get("source") or "poundcake")
    visibility = _text(
        payload.get("visibility")
        or canonical.get("route", {}).get("provider_config", {}).get("visibility")
    )

    if provider == "rackspace_core":
        rendered = _render_bbcode_sections(model)
        if action == "create":
            return {
                "subject": model["title"],
                "body": rendered,
                "source": source,
                "severity": _text(canonical.get("alert", {}).get("severity")),
            }
        if action == "comment":
            return {"comment": rendered, "source": source, "visibility": visibility}
        if action == "close":
            return {"close_notes": rendered, "source": source, "visibility": visibility}
        return {}

    if provider == "jira":
        rendered = _render_adf_sections(model)
        if action == "create":
            return {
                "title": model["title"],
                "description": rendered,
            }
        if action == "comment":
            return {"comment": rendered}
        if action == "close":
            return {"close_notes": rendered}
        return {}

    if provider == "github":
        rendered = _render_markdown_sections(model)
        if action == "create":
            return {"title": model["title"], "description": rendered}
        if action == "comment":
            return {"comment": rendered}
        if action == "close":
            return {"close_notes": rendered}
        return {}

    if provider == "servicenow":
        rendered = _render_plain_sections(model)
        if action == "create":
            return {
                "title": model["title"],
                "description": rendered,
            }
        if action == "comment":
            return {"comment": rendered}
        if action == "close":
            return {"close_notes": rendered}
        return {}

    if provider == "pagerduty":
        rendered = _render_plain_sections(model)
        if action == "create":
            return {"title": model["title"], "description": rendered}
        if action == "comment":
            return {"comment": rendered}
        if action == "close":
            return {"close_notes": rendered}
        return {}

    if provider == "teams":
        rendered = _render_plain_sections(model)
        return {"message": rendered}

    if provider == "discord":
        return _render_discord_message(model)

    return {}

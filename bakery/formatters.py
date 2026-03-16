#!/usr/bin/env python3
"""Provider-native communication renderers for Bakery."""

from __future__ import annotations

import re
from typing import Any, cast

URL_RE = re.compile(r"(https?://[^\s<>\]]+)")
AUTH_HEADER_RE = re.compile(r"(?im)\b(authorization\s*:\s*(?:bearer|basic)\s+)[^\s]+")
SECRET_KV_RE = re.compile(
    r"(?im)\b("
    r"api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|"
    r"webhook(?:_url)?|cookie"
    r")\b(\s*[:=]\s*)([^\s,;]+)"
)
QUERY_SECRET_RE = re.compile(
    r"([?&](?:access_token|token|api[_-]?key|apikey|sig|signature|password|secret|webhook_url)=)"
    r"[^&\s]+",
    re.IGNORECASE,
)
WEBHOOK_URL_RE = re.compile(
    r"https?://(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services|"
    r"outlook\.office\.com/webhook)[^\s]+",
    re.IGNORECASE,
)
URL_CREDENTIALS_RE = re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@", re.IGNORECASE)

FULL_STEP_LIMIT = 8
COMPACT_STEP_LIMIT = 3
FULL_STEP_OUTCOME_LIMIT = 180
COMPACT_STEP_OUTCOME_LIMIT = 90
FULL_EXCERPT_LIMIT = 900
COMPACT_EXCERPT_LIMIT = 260


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _collapse_line(value: Any) -> str:
    return " ".join(_text(value).split()).strip()


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


def _redact_sensitive_text(text: str) -> str:
    if not text:
        return ""

    text = AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = SECRET_KV_RE.sub(r"\1\2[REDACTED]", text)
    text = QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = WEBHOOK_URL_RE.sub("[REDACTED_WEBHOOK_URL]", text)
    text = URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", text)
    return text


def _sanitize_multiline_text(value: Any, limit: int) -> str:
    raw = _redact_sensitive_text(_text(value)).replace("\r\n", "\n")
    if not raw:
        return ""
    lines = [line.rstrip() for line in raw.split("\n")]
    normalized: list[str] = []
    pending_blank = False
    for line in lines:
        if line.strip():
            normalized.append(line.strip())
            pending_blank = False
            continue
        if normalized and not pending_blank:
            normalized.append("")
            pending_blank = True
    return _truncate("\n".join(normalized).strip(), limit)


def _sanitize_line(value: Any, limit: int) -> str:
    sanitized = _collapse_line(_redact_sensitive_text(_text(value)))
    return _truncate(sanitized, limit)


def _pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"


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
    context = _mapping(payload.get("context"))
    labels = _mapping(context.get("labels"))
    annotations = _mapping(context.get("annotations"))
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
            "provider_config": _mapping(context.get("provider_config")),
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
        "remediation": {
            "summary": {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0, "incomplete": 0},
            "steps": [],
            "before_excerpt": "",
            "after_excerpt": "",
            "failure_excerpt": "",
            "latest_completed_step": None,
        },
    }


def canonical_from_payload(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = _mapping(payload.get("context"))
    canonical = context.get("_canonical")
    if isinstance(canonical, dict):
        return cast(dict[str, Any], canonical)
    return _build_fallback_canonical(action, payload)


def provider_config_from_context(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    context = _mapping(payload.get("context"))
    provider_config = dict(_mapping(context.get("provider_config")))
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
    raw_links = canonical.get("links")
    link_items = (
        [cast(dict[str, Any], item) for item in raw_links if isinstance(item, dict)]
        if isinstance(raw_links, list)
        else []
    )
    normalized = [
        {"label": _text(item.get("label")), "url": _text(item.get("url"))} for item in link_items
    ]
    return _dedupe_links(normalized)


def _title_from_canonical(canonical: dict[str, Any]) -> str:
    text = _mapping(canonical.get("text"))
    alert = _mapping(canonical.get("alert"))
    annotations = _mapping(alert.get("annotations"))
    headline = _text(text.get("headline"))
    summary = _text(annotations.get("summary"))
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


def _pretty_status(value: Any) -> str:
    normalized = _collapse_line(value).lower().replace("_", " ")
    if normalized == "incomplete":
        return "in progress"
    return normalized


def _remediation_summary_line(summary: dict[str, Any]) -> str:
    total = int(summary.get("total") or 0)
    if total <= 0:
        return ""
    parts = [f"{_pluralize(total, 'step')} recorded"]
    for key in ("succeeded", "failed", "skipped", "incomplete"):
        count = int(summary.get(key) or 0)
        if count:
            if key == "incomplete":
                parts.append(f"{count} in progress")
            else:
                parts.append(_pluralize(count, key))
    return ": ".join((parts[0], ", ".join(parts[1:]))) if len(parts) > 1 else parts[0]


def _step_line(step: dict[str, Any], *, outcome_limit: int) -> str:
    label = _sanitize_line(step.get("task_key") or "step", 120)
    status = _pretty_status(step.get("status"))
    outcome = _sanitize_line(step.get("outcome"), outcome_limit)
    parts = [item for item in (label, status) if item]
    line = " - ".join(parts)
    if outcome and outcome.lower() not in line.lower():
        line = f"{line} - {outcome}" if line else outcome
    return f"- {line}".strip()


def _latest_step_line(step: dict[str, Any] | None, *, outcome_limit: int) -> str:
    if not isinstance(step, dict):
        return ""
    rendered = _step_line(step, outcome_limit=outcome_limit).removeprefix("- ").strip()
    if not rendered:
        return ""
    return f"Latest completed step: {rendered}"


def _pick_remediation_excerpts(
    remediation: dict[str, Any],
    *,
    remediation_outcome: str,
    action: str,
    excerpt_limit: int,
) -> dict[str, str]:
    failure_excerpt = _sanitize_multiline_text(remediation.get("failure_excerpt"), excerpt_limit)
    before_excerpt = _sanitize_multiline_text(remediation.get("before_excerpt"), excerpt_limit)
    after_excerpt = _sanitize_multiline_text(remediation.get("after_excerpt"), excerpt_limit)
    normalized_outcome = remediation_outcome.lower()
    normalized_action = action.lower()

    if failure_excerpt and normalized_outcome not in {"succeeded", "success"}:
        return {"failure_excerpt": failure_excerpt}
    if normalized_outcome in {"succeeded", "success"} or normalized_action == "close":
        excerpts: dict[str, str] = {}
        if before_excerpt:
            excerpts["before_excerpt"] = before_excerpt
        if after_excerpt:
            excerpts["after_excerpt"] = after_excerpt
        return excerpts
    if failure_excerpt:
        return {"failure_excerpt": failure_excerpt}
    if before_excerpt and normalized_action == "comment":
        return {"before_excerpt": before_excerpt}
    return {}


def _build_remediation_model(
    canonical: dict[str, Any],
    action: str,
    *,
    compact: bool,
) -> dict[str, Any]:
    remediation = _mapping(canonical.get("remediation"))
    order = _mapping(canonical.get("order"))
    summary = _mapping(remediation.get("summary"))
    raw_steps = (
        cast(list[Any], remediation.get("steps"))
        if isinstance(remediation.get("steps"), list)
        else []
    )
    step_items = [cast(dict[str, Any], step) for step in raw_steps if isinstance(step, dict)]
    latest_completed_step = (
        _mapping(remediation.get("latest_completed_step"))
        if isinstance(remediation.get("latest_completed_step"), dict)
        else {}
    )

    step_limit = COMPACT_STEP_LIMIT if compact else FULL_STEP_LIMIT
    outcome_limit = COMPACT_STEP_OUTCOME_LIMIT if compact else FULL_STEP_OUTCOME_LIMIT
    excerpt_limit = COMPACT_EXCERPT_LIMIT if compact else FULL_EXCERPT_LIMIT

    step_lines = [_step_line(step, outcome_limit=outcome_limit) for step in step_items[:step_limit]]
    hidden_steps = max(len(step_items) - len(step_lines), 0)
    if hidden_steps:
        step_lines.append(f"- ... {_pluralize(hidden_steps, 'more step')}")

    excerpts = _pick_remediation_excerpts(
        remediation,
        remediation_outcome=_text(order.get("remediation_outcome")),
        action=action,
        excerpt_limit=excerpt_limit,
    )

    return {
        "summary": _remediation_summary_line(summary),
        "latest": (
            _latest_step_line(latest_completed_step, outcome_limit=outcome_limit)
            if action == "comment"
            else ""
        ),
        "steps": step_lines,
        "before_excerpt": excerpts.get("before_excerpt", ""),
        "after_excerpt": excerpts.get("after_excerpt", ""),
        "failure_excerpt": excerpts.get("failure_excerpt", ""),
    }


def _section_model(canonical: dict[str, Any], action: str, *, compact: bool) -> dict[str, Any]:
    text = _mapping(canonical.get("text"))
    alert = _mapping(canonical.get("alert"))
    annotations = _mapping(alert.get("annotations"))
    order = _mapping(canonical.get("order"))
    event = _mapping(canonical.get("event"))

    headline = _sanitize_line(_text(text.get("headline")) or _title_from_canonical(canonical), 255)
    overview_lines: list[str] = []
    for line in (
        _sanitize_line(text.get("summary"), 500),
        _sanitize_line(text.get("detail"), 500),
        _sanitize_line(annotations.get("summary"), 500),
        _sanitize_line(annotations.get("description"), 500),
        _sanitize_line(annotations.get("customer_impact"), 500),
        _sanitize_line(annotations.get("suggested_action"), 500),
    ):
        if line and line not in overview_lines:
            overview_lines.append(line)
    if action == "close":
        resolution = _sanitize_line(text.get("resolution"), 500)
        if resolution:
            overview_lines.insert(0, resolution)

    links = _known_links(canonical)
    metadata = [
        ("Alert", _sanitize_line(alert.get("group_name"), 255)),
        ("Severity", _sanitize_line(alert.get("severity"), 64)),
        ("Status", _sanitize_line(alert.get("status"), 64)),
        ("Instance", _sanitize_line(alert.get("instance"), 255)),
        ("Fingerprint", _sanitize_line(alert.get("fingerprint"), 255)),
        ("Started", _sanitize_line(alert.get("starts_at"), 64)),
        ("Ended", _sanitize_line(alert.get("ends_at"), 64)),
        ("Order", _sanitize_line(order.get("id"), 64)),
        ("Request", _sanitize_line(order.get("req_id"), 128)),
    ]
    metadata = [(label, value) for label, value in metadata if value]
    return {
        "headline": headline,
        "title": _sanitize_line(_title_from_canonical(canonical), 255),
        "overview": overview_lines,
        "links": links,
        "metadata": metadata,
        "severity": _text(alert.get("severity") or "unknown"),
        "alert_status": _text(alert.get("status")),
        "event_name": _text(event.get("name")),
        "operation": _text(event.get("operation") or action),
        "remediation_outcome": _text(order.get("remediation_outcome")),
        "remediation": _build_remediation_model(canonical, action, compact=compact),
    }


def _markdown_code_text(text: str) -> str:
    return text.replace("```", "'''")


def _bbcode_code_text(text: str) -> str:
    return text.replace("[code]", "[ code]").replace("[/code]", "[/ code]")


def _render_plain_sections(model: dict[str, Any]) -> str:
    remediation = model["remediation"]
    parts = [model["headline"]]
    if model["overview"]:
        parts.append("")
        parts.append("Overview")
        parts.extend(model["overview"])
    if remediation["summary"] or remediation["latest"] or remediation["steps"]:
        parts.append("")
        parts.append("Remediation")
        if remediation["summary"]:
            parts.append(remediation["summary"])
        if remediation["latest"]:
            parts.append(remediation["latest"])
        parts.extend(remediation["steps"])
    for heading, body in (
        ("Failure excerpt", remediation["failure_excerpt"]),
        ("Before remediation excerpt", remediation["before_excerpt"]),
        ("After remediation excerpt", remediation["after_excerpt"]),
    ):
        if body:
            parts.append("")
            parts.append(heading)
            parts.append(body)
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
    remediation = model["remediation"]
    parts = [f"## {model['headline']}"]
    if model["overview"]:
        parts.append("")
        parts.append("**Overview**")
        parts.extend(_auto_link_markdown(line) for line in model["overview"])
    if remediation["summary"] or remediation["latest"] or remediation["steps"]:
        parts.append("")
        parts.append("**Remediation**")
        if remediation["summary"]:
            parts.append(remediation["summary"])
        if remediation["latest"]:
            parts.append(remediation["latest"])
        parts.extend(remediation["steps"])
    for heading, body in (
        ("Failure excerpt", remediation["failure_excerpt"]),
        ("Before remediation excerpt", remediation["before_excerpt"]),
        ("After remediation excerpt", remediation["after_excerpt"]),
    ):
        if body:
            parts.append("")
            parts.append(f"**{heading}**")
            parts.append(f"```text\n{_markdown_code_text(body)}\n```")
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
    remediation = model["remediation"]
    parts = [f"[b]{_auto_link_bbcode(model['headline'])}[/b]"]
    if model["overview"]:
        parts.append("")
        parts.append("[b]Overview[/b]")
        parts.extend(_auto_link_bbcode(line) for line in model["overview"])
    if remediation["summary"] or remediation["latest"] or remediation["steps"]:
        parts.append("")
        parts.append("[b]Remediation[/b]")
        if remediation["summary"]:
            parts.append(_auto_link_bbcode(remediation["summary"]))
        if remediation["latest"]:
            parts.append(_auto_link_bbcode(remediation["latest"]))
        parts.extend(_auto_link_bbcode(line) for line in remediation["steps"])
    for heading, body in (
        ("Failure excerpt", remediation["failure_excerpt"]),
        ("Before remediation excerpt", remediation["before_excerpt"]),
        ("After remediation excerpt", remediation["after_excerpt"]),
    ):
        if body:
            parts.append("")
            parts.append(f"[b]{heading}[/b]")
            parts.append(f"[code]{_bbcode_code_text(body)}[/code]")
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


def _adf_code_block(text: str) -> dict[str, Any]:
    return {"type": "codeBlock", "attrs": {}, "content": [{"type": "text", "text": text}]}


def _render_adf_sections(model: dict[str, Any]) -> dict[str, Any]:
    remediation = model["remediation"]
    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 2}, "content": _adf_text_nodes(model["headline"])}
    ]
    if model["overview"]:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes("Overview")}
        )
        content.extend(_adf_paragraph(line) for line in model["overview"])
    if remediation["summary"] or remediation["latest"] or remediation["steps"]:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes("Remediation")}
        )
        if remediation["summary"]:
            content.append(_adf_paragraph(remediation["summary"]))
        if remediation["latest"]:
            content.append(_adf_paragraph(remediation["latest"]))
        if remediation["steps"]:
            content.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [_adf_paragraph(line.removeprefix("- ").strip())],
                        }
                        for line in remediation["steps"]
                    ],
                }
            )
    for heading, body in (
        ("Failure excerpt", remediation["failure_excerpt"]),
        ("Before remediation excerpt", remediation["before_excerpt"]),
        ("After remediation excerpt", remediation["after_excerpt"]),
    ):
        if body:
            content.append(
                {"type": "heading", "attrs": {"level": 3}, "content": _adf_text_nodes(heading)}
            )
            content.append(_adf_code_block(body))
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
    remediation = model["remediation"]
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
    remediation_lines: list[str] = []
    if remediation["summary"]:
        remediation_lines.append(remediation["summary"])
    if remediation["latest"]:
        remediation_lines.append(remediation["latest"])
    remediation_lines.extend(line.removeprefix("- ").strip() for line in remediation["steps"])
    if remediation_lines:
        fields.append(
            {
                "name": "Remediation",
                "value": _truncate("\n".join(remediation_lines), 1000),
                "inline": False,
            }
        )
    excerpt_label = ""
    excerpt_body = ""
    for label, body in (
        ("Failure excerpt", remediation["failure_excerpt"]),
        ("After remediation excerpt", remediation["after_excerpt"]),
        ("Before remediation excerpt", remediation["before_excerpt"]),
    ):
        if body:
            excerpt_label = label
            excerpt_body = body
            break
    if excerpt_body:
        fields.append(
            {
                "name": excerpt_label,
                "value": _truncate(excerpt_body, 1000),
                "inline": False,
            }
        )
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
    model = _section_model(canonical, action, compact=provider in {"teams", "discord"})
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

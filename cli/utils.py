"""Utility functions for CLI parsing and output formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import click
import yaml

TableRenderer = Callable[[Any], str]


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def format_output(data: Any, format: str = "table") -> str:
    if format == "json":
        return json.dumps(data, indent=2, sort_keys=False)
    if format == "yaml":
        return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    if format == "table":
        return format_table(data)
    return str(data)


def format_table(data: Any) -> str:
    if isinstance(data, dict):
        if not data:
            return "No data"
        width = max(len(str(key)) for key in data.keys())
        lines = []
        for key, value in data.items():
            rendered = _table_value(value)
            lines.append(f"{str(key).ljust(width)}  {rendered}")
        return "\n".join(lines)

    if isinstance(data, list):
        if not data:
            return "No items"
        if not isinstance(data[0], dict):
            return "\n".join(str(item) for item in data)

        keys = list(data[0].keys())
        widths = {key: len(str(key)) for key in keys}
        rendered_rows: list[dict[str, str]] = []
        for item in data:
            rendered_row: dict[str, str] = {}
            for key in keys:
                rendered = _table_value(item.get(key, ""))
                if len(rendered) > 72:
                    rendered = rendered[:69] + "..."
                rendered_row[key] = rendered
                widths[key] = max(widths[key], len(rendered))
            rendered_rows.append(rendered_row)

        header = "  ".join(str(key).ljust(widths[key]) for key in keys)
        separator = "  ".join("-" * widths[key] for key in keys)
        rows = [
            "  ".join(rendered_row[key].ljust(widths[key]) for key in keys)
            for rendered_row in rendered_rows
        ]
        return "\n".join([header, separator, *rows])

    return str(data)


def _table_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return compact_json(value)
    if value is None:
        return "-"
    return str(value)


def print_output(
    data: Any, format: str = "table", *, table_renderer: TableRenderer | None = None
) -> None:
    if format == "table" and table_renderer is not None:
        click.echo(table_renderer(data))
        return
    click.echo(format_output(data, format))


def print_success(message: str) -> None:
    click.echo(click.style(f"OK: {message}", fg="green"))


def print_error(message: str) -> None:
    click.echo(click.style(f"ERROR: {message}", fg="red"), err=True)


def print_warning(message: str) -> None:
    click.echo(click.style(f"WARN: {message}", fg="yellow"))


def print_info(message: str) -> None:
    click.echo(click.style(f"INFO: {message}", fg="blue"))


def parse_json_value(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{label} must be valid JSON: {exc}") from exc


def parse_json_object(value: str | None, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = parse_json_value(value, label)
    if not isinstance(parsed, dict):
        raise click.BadParameter(f"{label} must decode to a JSON object")
    return parsed


def load_data_file(path: Path) -> Any:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise click.FileError(str(path), hint=str(exc)) from exc
    if loaded is None:
        return {}
    return loaded


def require_mapping(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise click.BadParameter(f"{label} must be an object")
    return data


def titleize(value: str | None) -> str:
    if not value:
        return "-"
    return str(value).replace("_", " ").strip().title()


def filter_by_search(
    rows: Sequence[dict[str, Any]],
    search: str | None,
    fields: Iterable[str],
) -> list[dict[str, Any]]:
    if not search:
        return list(rows)
    needle = search.lower()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(str(row.get(field) or "") for field in fields).lower()
        if needle in haystack:
            filtered.append(row)
    return filtered


def render_sections(sections: Sequence[tuple[str, Any]]) -> str:
    rendered: list[str] = []
    for title, value in sections:
        rendered.append(title)
        rendered.append("=" * len(title))
        if isinstance(value, str):
            rendered.append(value)
        else:
            rendered.append(format_table(value))
        rendered.append("")
    return "\n".join(rendered).rstrip()

"""Shared helpers for CLI command modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import click

from cli.client import PoundCakeClient
from cli.utils import load_data_file, require_mapping


def get_client(ctx: click.Context) -> PoundCakeClient:
    return cast(PoundCakeClient, ctx.obj["client"])


def get_output_format(ctx: click.Context) -> str:
    return cast(str, ctx.obj["format"])


def read_mapping_file(path: Path, label: str) -> dict[str, Any]:
    return require_mapping(load_data_file(path), label)


def compact_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}

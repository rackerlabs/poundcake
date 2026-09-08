"""Tests for mission-control observability feeds."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from api.api.observability import _load_communication_activity


class _EmptyResult:
    def all(self) -> list[Any]:
        return []


class _CapturingDb:
    def __init__(self) -> None:
        self.statement: Any = None

    async def execute(self, statement: Any) -> _EmptyResult:
        self.statement = statement
        return _EmptyResult()


@pytest.mark.asyncio
async def test_communication_activity_only_loads_comms_ingredients() -> None:
    db = _CapturingDb()

    await _load_communication_activity(db, limit=25)  # type: ignore[arg-type]

    compiled = str(
        db.statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "ingredients.ingredient_purpose = 'comms'" in compiled
    assert "JOIN recipe_ingredients" in compiled
    assert "JOIN ingredients" in compiled


@pytest.mark.asyncio
async def test_communication_activity_keeps_health_check_comms_rows() -> None:
    db = _CapturingDb()

    await _load_communication_activity(  # type: ignore[arg-type]
        db,
        exclude_plugin_health_checks=True,
        limit=25,
    )

    compiled = str(
        db.statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "plugin-health-check" not in compiled


def test_timeline_order_includes_alert_context() -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from api.api.orders import _serialize_timeline_order

    now = datetime(2026, 7, 8, tzinfo=timezone.utc)
    order = SimpleNamespace(
        id=88,
        req_id="req-88",
        raw_data={"order_type": "webhook_alert", "generatorURL": "https://prom.example/graph"},
        alert_status="firing",
        alert_group_name="NodeDown",
        processing_status="resolving",
        is_active=True,
        remediation_outcome="pending",
        clear_timeout_sec=300,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        severity="critical",
        instance="compute-1",
        correlation_key="node:compute-1",
        counter=1,
        starts_at=now,
        ends_at=None,
        order_lifetime_secs=None,
        communications=[],
        created_at=now,
        updated_at=now,
        labels={"instance": "compute-1", "namespace": "openstack"},
        annotations={
            "summary": "Node compute-1 is down",
            "runbook_url": "https://runbooks.example/node",
        },
        fingerprint="fp-88",
        fingerprint_when_active="fp-88",
    )

    payload = _serialize_timeline_order(order)  # type: ignore[arg-type]
    assert payload.fingerprint == "fp-88"
    assert payload.annotations["summary"] == "Node compute-1 is down"
    assert payload.raw_data["generatorURL"] == "https://prom.example/graph"
    assert payload.labels["namespace"] == "openstack"

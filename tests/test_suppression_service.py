"""Unit tests for suppression service matching logic."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from api.models.models import AlertSuppression, AlertSuppressionMatcher, SuppressionSummary
from api.services.suppression_service import (
    _matcher_match,
    build_summary_ticket_payload,
    find_first_matching_suppression,
    suppression_matches,
    suppression_status,
)


class ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _suppression(scope: str = "matchers", created_offset: int = 0) -> AlertSuppression:
    now = datetime.now(timezone.utc)
    return AlertSuppression(
        id=1 + created_offset,
        name=f"s-{created_offset}",
        scope=scope,
        enabled=True,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=5),
        created_at=now + timedelta(seconds=created_offset),
        updated_at=now,
        matchers=[],
        summary_ticket_enabled=True,
    )


def test_matcher_operators():
    labels = {"alertname": "NodeDown", "severity": "critical", "instance": "node-1"}
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="severity", operator="eq", value="critical"),
        labels,
    )
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="severity", operator="neq", value="warning"),
        labels,
    )
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="alertname", operator="regex", value="Node.*"),
        labels,
    )
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="alertname", operator="nregex", value="CPU.*"),
        labels,
    )
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="instance", operator="exists", value=None),
        labels,
    )
    assert _matcher_match(
        AlertSuppressionMatcher(label_key="pod", operator="not_exists", value=None),
        labels,
    )


def test_suppression_matches_scope_all():
    suppression = _suppression(scope="all")
    assert suppression_matches(suppression, {"anything": "goes"})


def test_suppression_status_variants():
    now = datetime.now(timezone.utc)
    active = AlertSuppression(
        id=1,
        name="active",
        scope="all",
        enabled=True,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(minutes=1),
        created_at=now,
        updated_at=now,
        summary_ticket_enabled=True,
    )
    assert suppression_status(active, now=now) == "active"
    active.canceled_at = now
    assert suppression_status(active, now=now) == "canceled"


def test_suppression_status_handles_naive_database_timestamps():
    now = datetime.now(timezone.utc)
    active = AlertSuppression(
        id=2,
        name="naive-active",
        scope="all",
        enabled=True,
        starts_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
        ends_at=(now + timedelta(minutes=1)).replace(tzinfo=None),
        created_at=now.replace(tzinfo=None),
        updated_at=now.replace(tzinfo=None),
        summary_ticket_enabled=True,
    )

    assert suppression_status(active, now=now) == "active"


@pytest.mark.asyncio
async def test_first_created_suppression_wins():
    db = AsyncMock()
    older = _suppression(created_offset=0)
    older.matchers = [
        AlertSuppressionMatcher(label_key="severity", operator="eq", value="critical")
    ]
    newer = _suppression(created_offset=1)
    newer.matchers = [
        AlertSuppressionMatcher(label_key="severity", operator="eq", value="critical")
    ]
    db.execute = AsyncMock(return_value=ScalarResult([older, newer]))

    selected = await find_first_matching_suppression(db, {"severity": "critical"})
    assert selected is not None
    assert selected.id == older.id


def test_summary_payload_contains_expected_sections():
    suppression = _suppression(scope="matchers")
    suppression.name = "maint-1"
    suppression.reason = "kernel patching"
    suppression.matchers = [
        AlertSuppressionMatcher(label_key="severity", operator="eq", value="warning")
    ]
    summary = SuppressionSummary(
        suppression_id=suppression.id,
        total_suppressed=12,
        by_alertname_json={"NodeDown": 10},
        by_severity_json={"warning": 12},
        first_seen_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        last_seen_at=datetime.now(timezone.utc),
        state="pending",
    )

    payload = build_summary_ticket_payload(suppression, summary)
    assert "PoundCake Suppression Summary" in payload["title"]
    assert "Total Suppressed: 12" in payload["description"]

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.api.suppressions import create_suppression
from api.models.models import AlertSuppression, AlertSuppressionMatcher
from api.schemas.schemas import SuppressionCreate, SuppressionMatcher


@pytest.mark.asyncio
async def test_create_suppression_normalizes_mixed_timezone_datetimes() -> None:
    request = SimpleNamespace(state=SimpleNamespace(req_id="test-req"))
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    created: dict[str, AlertSuppression | AlertSuppressionMatcher] = {}

    def add_item(item):
        if isinstance(item, AlertSuppression):
            item.id = 42
            item.created_at = datetime(2026, 4, 28, tzinfo=timezone.utc)
            item.updated_at = datetime(2026, 4, 28, tzinfo=timezone.utc)
            created["suppression"] = item
        elif isinstance(item, AlertSuppressionMatcher):
            created["matcher"] = item

    db.add = Mock(side_effect=add_item)
    payload = SuppressionCreate(
        name="Ceph storage page faults",
        reason="Known low-memory storage nodes",
        starts_at=datetime(2099, 1, 1, 12, 0, 0),
        ends_at=datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        scope="matchers",
        matchers=[
            SuppressionMatcher(
                label_key="alertname",
                operator="regex",
                value=r"^node-memory-major-pages-faults-(warning|critical)$",
            )
        ],
        created_by="ui-v2",
        summary_ticket_enabled=False,
        enabled=True,
    )

    async def fake_get_suppression(_db, _suppression_id):
        suppression = created["suppression"]
        suppression.matchers = [created["matcher"]]
        return suppression

    with patch("api.api.suppressions.get_suppression", side_effect=fake_get_suppression):
        response = await create_suppression(request, payload, db)

    assert response.id == 42
    assert response.ends_at.year == 9999
    suppression = created["suppression"]
    assert suppression.starts_at.tzinfo == timezone.utc
    assert suppression.ends_at.tzinfo == timezone.utc

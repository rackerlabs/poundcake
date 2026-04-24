from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from api.models.models import (
    ReleaseUpdateNotification,
    ReleaseUpdateNotificationDelivery,
)
from api.services.communications_policy import POLICY_METADATA_KEY, CommunicationRoute
from api.services import release_update_notifications as updates


class _FakeBegin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return _FakeBegin()


def _response(
    status_code: int,
    url: str,
    *,
    json_payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_payload or {},
        headers=headers or {},
        request=httpx.Request("GET", url),
    )


@pytest.mark.asyncio
async def test_oci_client_uses_bearer_token_paginates_and_ranks_by_app_version(monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    manifests = {
        "0.2.1": ("sha256:cfg-021", "0.2.1", "1.0.0"),
        "0.2.2": ("sha256:cfg-022", "0.2.2", "1.1.0"),
        "2.0.96": ("sha256:cfg-2096", "2.0.96", "0.9.0"),
        "0.2.3": ("sha256:cfg-023", "0.2.3", "1.2.0"),
        "0.2.4-alpha": ("sha256:cfg-024a", "0.2.4-alpha", "1.3.0-alpha.1"),
    }

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        headers = kwargs.get("headers") or {}
        if "token" in url:
            return _response(200, url, json_payload={"token": "registry-token"})
        if url.endswith("/tags/list?n=100") and "Authorization" not in headers:
            return _response(
                401,
                url,
                json_payload={"errors": []},
                headers={
                    "www-authenticate": (
                        'Bearer realm="https://ghcr.io/token",service="ghcr.io",'
                        'scope="repository:rackerlabs/charts/poundcake:pull"'
                    )
                },
            )
        if url.endswith("/tags/list?n=100"):
            return _response(
                200,
                url,
                json_payload={"tags": ["0.2.1", "0.2.2"]},
                headers={
                    "link": (
                        "</v2/rackerlabs/charts/poundcake/tags/list?n=100&last=0.2.2>; "
                        'rel="next"'
                    )
                },
            )
        if "tags/list?n=100&last=0.2.2" in url:
            return _response(
                200,
                url,
                json_payload={"tags": ["2.0.96", "0.2.3", "not-a-version", "0.2.4-alpha"]},
            )
        for tag, (digest, chart_version, app_version) in manifests.items():
            if url.endswith(f"/manifests/{tag}"):
                return _response(
                    200,
                    url,
                    json_payload={
                        "config": {"digest": digest},
                        "annotations": {"org.opencontainers.image.created": "2026-04-22T17:30:15Z"},
                    },
                )
            if url.endswith(f"/blobs/{digest}"):
                return _response(
                    200,
                    url,
                    json_payload={"version": chart_version, "appVersion": app_version},
                )
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(updates, "request_with_retry", fake_request)

    client = updates.OciChartClient(oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake")
    latest = await client.fetch_latest_release(include_prereleases=False)

    assert latest is not None
    assert latest.chart_version == "0.2.3"
    assert latest.app_version == "1.2.0"
    assert latest.created_at == datetime(2026, 4, 22, 17, 30, 15, tzinfo=timezone.utc)
    assert any("https://ghcr.io/token" in url for _method, url, _kwargs in calls)
    assert any(
        (kwargs.get("headers") or {}).get("Authorization") == "Bearer registry-token"
        for _method, url, kwargs in calls
        if "/manifests/" in url
    )


def test_release_newer_logic_uses_app_version_before_chart_version():
    assert not updates.is_release_newer(
        updates.OciChartRelease(chart_version="2.0.96", app_version="2.0.96"),
        current_app_version="2.0.204",
        current_chart_version="0.2.103",
    )
    assert updates.is_release_newer(
        updates.OciChartRelease(chart_version="0.2.104", app_version="2.0.205"),
        current_app_version="2.0.204",
        current_chart_version="0.2.103",
    )
    assert updates.is_release_newer(
        updates.OciChartRelease(chart_version="0.2.104", app_version="2.0.204"),
        current_app_version="2.0.204",
        current_chart_version="0.2.103",
    )


def test_advisory_payload_targets_snapshot_global_route():
    notification = ReleaseUpdateNotification(
        id=7,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="2.0.204",
        current_chart_version="0.2.103",
        available_app_version="2.0.205",
        available_chart_version="0.2.104",
        state="pending",
    )
    delivery = ReleaseUpdateNotificationDelivery(
        id=9,
        notification_id=7,
        route_id="core-route",
        route_label="Rackspace Core",
        execution_target="rackspace_core",
        destination_target="",
        provider_config={"account_number": "5002029"},
        state="pending",
    )

    payload = updates.build_advisory_payload(notification, delivery)

    assert payload["title"] == "[PoundCake Update Available] 2.0.205 available"
    assert "PoundCake did not perform an automatic upgrade" in payload["description"]
    assert payload["source"] == "poundcake_system"
    assert payload["context"]["execution_target"] == "rackspace_core"
    assert payload["context"]["provider_config"] == {"account_number": "5002029"}
    assert payload["context"][POLICY_METADATA_KEY]["route_id"] == "core-route"


@pytest.mark.asyncio
async def test_snapshot_routes_creates_once_and_blocks_without_global_policy(monkeypatch):
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        add=Mock(),
        flush=AsyncMock(),
    )
    route = CommunicationRoute(
        id="discord-route",
        label="Discord",
        execution_target="discord",
        destination_target="ops",
        provider_config={},
        enabled=True,
        position=1,
    )
    monkeypatch.setattr(updates, "get_global_policy_routes", AsyncMock(return_value=[route]))
    notification = ReleaseUpdateNotification(
        id=11,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.1.0",
        available_chart_version="0.2.0",
        state="pending",
        deliveries=[],
    )

    deliveries = await updates._snapshot_routes_if_needed(db, notification)

    assert len(deliveries) == 1
    assert deliveries[0].route_id == "discord-route"
    assert notification.state == "notifying"
    db.add.assert_called_once()

    db.scalar = AsyncMock(return_value=1)
    notification.deliveries = deliveries
    monkeypatch.setattr(updates, "get_global_policy_routes", AsyncMock(side_effect=AssertionError))
    assert await updates._snapshot_routes_if_needed(db, notification) == deliveries

    blocked_db = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(updates, "get_global_policy_routes", AsyncMock(return_value=[]))
    blocked = ReleaseUpdateNotification(
        id=12,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.2.0",
        available_chart_version="0.3.0",
        state="pending",
        deliveries=[],
    )

    assert await updates._snapshot_routes_if_needed(blocked_db, blocked) == []
    assert blocked.state == "blocked"
    assert "No enabled global communications routes" in (blocked.latest_error or "")


@pytest.mark.asyncio
async def test_notified_release_short_circuits_future_advisories(monkeypatch):
    notification = ReleaseUpdateNotification(
        id=21,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.1.0",
        available_chart_version="0.2.0",
        state=updates.NOTIFIED_STATE,
        deliveries=[],
    )
    monkeypatch.setattr(updates, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        updates,
        "get_settings",
        lambda: SimpleNamespace(bakery_enabled=True, bakery_base_url="http://bakery"),
    )
    get_or_create = AsyncMock(return_value=notification)
    snapshot = AsyncMock(side_effect=AssertionError("notified release should not resnapshot"))
    monkeypatch.setattr(updates, "_get_or_create_notification", get_or_create)
    monkeypatch.setattr(updates, "_snapshot_routes_if_needed", snapshot)

    status = await updates.process_release_notification(
        updates.OciChartRelease(chart_version="0.2.0", app_version="1.1.0")
    )

    assert status == updates.NOTIFIED_STATE
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_delivery_retries_only_unsucceeded_snapshot_routes(monkeypatch):
    notification = ReleaseUpdateNotification(
        id=22,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.1.0",
        available_chart_version="0.2.0",
        state="failed",
    )
    succeeded = ReleaseUpdateNotificationDelivery(
        id=31,
        notification_id=22,
        route_id="core-route",
        route_label="Rackspace Core",
        execution_target="rackspace_core",
        destination_target="",
        provider_config={"account_number": "5002029"},
        state=updates.SUCCEEDED_DELIVERY_STATE,
    )
    failed = ReleaseUpdateNotificationDelivery(
        id=32,
        notification_id=22,
        route_id="discord-route",
        route_label="Discord",
        execution_target="discord",
        destination_target="ops",
        provider_config={},
        state="failed",
    )
    deliveries = [succeeded, failed]
    notification.deliveries = deliveries
    monkeypatch.setattr(updates, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        updates,
        "get_settings",
        lambda: SimpleNamespace(bakery_enabled=True, bakery_base_url="http://bakery"),
    )
    deliver = AsyncMock()
    finalize = AsyncMock(return_value=updates.NOTIFIED_STATE)
    monkeypatch.setattr(
        updates, "_get_or_create_notification", AsyncMock(return_value=notification)
    )
    monkeypatch.setattr(updates, "_snapshot_routes_if_needed", AsyncMock(return_value=deliveries))
    monkeypatch.setattr(updates, "_deliver_route", deliver)
    monkeypatch.setattr(updates, "_finalize_notification", finalize)

    status = await updates.process_release_notification(
        updates.OciChartRelease(chart_version="0.2.0", app_version="1.1.0")
    )

    assert status == updates.NOTIFIED_STATE
    deliver.assert_awaited_once_with(notification, failed)
    finalize.assert_awaited_once_with(notification.id)


def test_idempotency_key_is_stable_per_release_and_route():
    delivery = ReleaseUpdateNotificationDelivery(
        id=41,
        notification_id=40,
        route_id="core-route",
        route_label="Rackspace Core",
        execution_target="rackspace_core",
        destination_target="",
        provider_config={},
        state="pending",
    )
    release_11 = ReleaseUpdateNotification(
        id=40,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.1.0",
        available_chart_version="0.2.0",
        state="pending",
    )
    release_12 = ReleaseUpdateNotification(
        id=42,
        oci_repository="oci://ghcr.io/rackerlabs/charts/poundcake",
        current_app_version="1.0.0",
        current_chart_version="0.1.0",
        available_app_version="1.2.0",
        available_chart_version="0.3.0",
        state="pending",
    )

    assert updates._idempotency_key(release_11, delivery) == updates._idempotency_key(
        release_11, delivery
    )
    assert updates._idempotency_key(release_11, delivery) != updates._idempotency_key(
        release_12, delivery
    )

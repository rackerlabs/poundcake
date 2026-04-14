from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from api.services import bakery_client
from api.services import bakery_monitor
from api.services.bakery_client import (
    BakeryTicketAccepted,
    BakeryTicketOperation,
    BakeryTicketResource,
)
from shared.bakery_contract import (
    CollectionJobClaimResponse,
    CollectionJobResponse,
    CommunicationAcceptedResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
    MonitorRouteCatalogEntry,
)


class _FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.status_code = status_code
        self.text = "ok"
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _client_settings() -> SimpleNamespace:
    return SimpleNamespace(
        bakery_base_url="https://bakery.example.com",
        bakery_request_timeout_seconds=30,
        bakery_max_retries=1,
        bakery_auth_mode="none",
        bakery_poll_timeout_seconds=1,
        bakery_poll_interval_seconds=0,
        bakery_hmac_key_id="",
        bakery_hmac_key="",
        bakery_bootstrap_hmac_key_id="",
        bakery_bootstrap_hmac_key="",
        bakery_secret_encryption_key="",
        bakery_monitor_id="",
        bakery_monitor_environment_label="example/poundcake",
        bakery_monitor_region="test-region",
        bakery_monitor_cluster_name="example-cluster",
        bakery_monitor_namespace="example-namespace",
        bakery_monitor_release_name="poundcake",
        bakery_monitor_tags=["shared-bakery", "example"],
        bakery_monitor_heartbeat_interval_seconds=30,
        bakery_collection_poll_interval_seconds=10,
    )


@pytest.mark.asyncio
async def test_ticket_wrappers_normalize_remote_communication_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        bakery_client,
        "open_communication_with_key",
        AsyncMock(
            return_value=CommunicationAcceptedResponse(
                communication_id="comm-4",
                operation_id="op-4",
                action="create",
                status="queued",
                created_at=now,
            )
        ),
    )
    monkeypatch.setattr(
        bakery_client,
        "get_communication",
        AsyncMock(
            return_value=CommunicationResponse(
                communication_id="comm-4",
                provider_type="rackspace_core",
                provider_reference_id="INC0004",
                state="open",
                latest_error=None,
                created_at=now,
                updated_at=now,
                communication_data={"title": "Alert"},
                last_sync_operation_id="op-4",
                last_sync_at=now,
            )
        ),
    )
    monkeypatch.setattr(
        bakery_client,
        "get_communication_operation",
        AsyncMock(
            return_value=CommunicationOperationResponse(
                operation_id="op-4",
                communication_id="comm-4",
                status="queued",
                action="open",
                attempt_count=0,
                max_attempts=5,
                created_at=now,
                updated_at=now,
            )
        ),
    )

    accepted = await bakery_client.create_ticket_with_key(
        req_id="REQ-1",
        payload={"title": "A", "description": "B"},
        idempotency_key="idem-4",
    )
    ticket = await bakery_client.get_ticket("comm-4")
    operation = await bakery_client.get_operation("op-4")

    assert isinstance(accepted, BakeryTicketAccepted)
    assert isinstance(ticket, BakeryTicketResource)
    assert isinstance(operation, BakeryTicketOperation)
    assert accepted.ticket_id == "comm-4"
    assert ticket.provider_ticket_id == "INC0004"
    assert ticket.ticket_data == {"title": "Alert"}
    assert operation.ticket_id == "comm-4"


@pytest.mark.asyncio
async def test_bakery_client_rejects_extra_fields_in_owned_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bakery_client, "get_settings", lambda: _client_settings())
    monkeypatch.setattr(
        bakery_client,
        "request_with_retry",
        AsyncMock(
            return_value=_FakeResponse(
                {
                    "communication_id": "comm-5",
                    "provider_type": "rackspace_core",
                    "state": "open",
                    "created_at": "2026-03-19T00:00:00Z",
                    "updated_at": "2026-03-19T00:00:00Z",
                    "unexpected": "boom",
                }
            )
        ),
    )

    with pytest.raises(ValidationError):
        await bakery_client.get_communication("comm-5")


@pytest.mark.asyncio
async def test_bakery_client_rejects_missing_required_fields_in_owned_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bakery_client, "get_settings", lambda: _client_settings())
    monkeypatch.setattr(
        bakery_client,
        "request_with_retry",
        AsyncMock(
            return_value=_FakeResponse(
                {
                    "communication_id": "comm-6",
                    "action": "create",
                    "status": "queued",
                    "created_at": "2026-03-19T00:00:00Z",
                }
            )
        ),
    )

    with pytest.raises(ValidationError):
        await bakery_client.open_communication_with_key(
            req_id="REQ-6",
            payload={"title": "Disk alert", "description": "details"},
            idempotency_key="idem-6",
        )


@pytest.mark.asyncio
async def test_prepare_managed_payload_normalizes_registered_route_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = MonitorRouteCatalogEntry(
        scope="global",
        owner_key="global",
        route_id="core-primary",
        label="Primary Core",
        execution_target="rackspace_core",
        destination_target="primary-core",
        provider_config={"account_number": "1234567"},
        enabled=True,
        outage_enabled=True,
        position=1,
    )

    class _FakeSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(bakery_monitor, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        bakery_monitor,
        "build_monitor_route_catalog",
        AsyncMock(return_value=[route]),
    )

    payload = {
        "title": "Disk alert",
        "description": "details",
        "source": "poundcake",
        "context": {
            "poundcake_policy": {
                "scope": "global",
                "owner_key": "global",
                "route_id": "core-primary",
                "execution_target": "rackspace_core",
                "destination_target": "primary-core",
                "provider_config": {"account_number": "1234567"},
            }
        },
    }

    normalized = await bakery_monitor.prepare_managed_payload(payload)

    assert normalized["context"]["scope"] == "global"
    assert normalized["context"]["owner_key"] == "global"
    assert normalized["context"]["route_id"] == "core-primary"
    assert normalized["context"]["provider_config"]["account_number"] == "1234567"


@pytest.mark.asyncio
async def test_prepare_managed_payload_allows_system_source_without_route_metadata() -> None:
    payload = {
        "title": "Suppression summary",
        "description": "details",
        "source": "poundcake_system",
        "context": {"source": "poundcake_system"},
    }

    normalized = await bakery_monitor.prepare_managed_payload(payload)

    assert normalized is payload


@pytest.mark.asyncio
async def test_bakery_client_uses_monitor_auth_headers_for_hmac_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _client_settings()
    settings.bakery_auth_mode = "hmac"
    settings.bakery_monitor_id = "example/poundcake"
    monkeypatch.setattr(bakery_client, "get_settings", lambda: settings)
    monkeypatch.setattr(
        bakery_client,
        "prepare_managed_payload",
        AsyncMock(
            return_value={
                "title": "Disk alert",
                "description": "details",
                "context": {
                    "scope": "global",
                    "owner_key": "global",
                    "route_id": "core-primary",
                },
            }
        ),
    )
    monkeypatch.setattr(
        bakery_client,
        "ensure_monitor_route_catalog_current",
        AsyncMock(return_value="hash-1"),
    )
    monkeypatch.setattr(
        bakery_client,
        "build_monitor_auth_headers",
        AsyncMock(
            return_value={
                "Authorization": "HMAC active:signature",
                "X-Timestamp": "1700000000",
                "X-Bakery-Monitor-UUID": "monitor-uuid-1",
            }
        ),
    )
    request = AsyncMock(
        return_value=_FakeResponse(
            {
                "communication_id": "comm-8",
                "operation_id": "op-8",
                "action": "open",
                "status": "queued",
                "created_at": "2026-03-19T00:00:00Z",
            }
        )
    )
    monkeypatch.setattr(bakery_client, "request_with_retry", request)

    accepted = await bakery_client.open_communication_with_key(
        req_id="REQ-8",
        payload={
            "title": "Disk alert",
            "description": "details",
            "context": {"scope": "global", "owner_key": "global", "route_id": "core-primary"},
        },
        idempotency_key="idem-8",
    )

    assert accepted.communication_id == "comm-8"
    sent_headers = request.await_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "HMAC active:signature"
    assert sent_headers["X-Bakery-Monitor-UUID"] == "monitor-uuid-1"


def test_monitor_registration_request_accepts_metadata_fields() -> None:
    payload = bakery_monitor.MonitorRegistrationRequest(
        monitor_id="example/poundcake",
        installation_id="pod-1",
        app_version="2.0.0",
        environment_label="example/poundcake",
        region="test-region",
        cluster_name="example-cluster",
        namespace="example-namespace",
        release_name="poundcake",
        tags=["shared-bakery", "example"],
    )

    assert payload.environment_label == "example/poundcake"
    assert payload.region == "test-region"
    assert payload.tags == ["shared-bakery", "example"]


@pytest.mark.asyncio
async def test_process_next_collection_job_completes_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bakery_monitor, "monitor_auth_enabled", lambda: True)
    monkeypatch.setattr(
        bakery_monitor,
        "claim_next_collection_job",
        AsyncMock(
            return_value=CollectionJobClaimResponse(
                available=True,
                job=CollectionJobResponse(
                    job_id="job-1",
                    monitor_uuid="monitor-1",
                    monitor_id="example/poundcake",
                    collector_type="monitor_diagnostics",
                    status="leased",
                    parameters={"include_health": True},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            )
        ),
    )
    monkeypatch.setattr(
        bakery_monitor,
        "run_collection_job",
        AsyncMock(return_value={"collector_type": "monitor_diagnostics"}),
    )
    complete = AsyncMock(
        return_value=CollectionJobResponse(
            job_id="job-1",
            monitor_uuid="monitor-1",
            monitor_id="example/poundcake",
            collector_type="monitor_diagnostics",
            status="succeeded",
            result={"collector_type": "monitor_diagnostics"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr(bakery_monitor, "complete_collection_job", complete)

    response = await bakery_monitor.process_next_collection_job()

    assert response is not None
    assert response.status == "succeeded"
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["job_id"] == "job-1"
    assert complete.await_args.kwargs["status"] == "succeeded"


@pytest.mark.asyncio
async def test_process_next_collection_job_marks_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bakery_monitor, "monitor_auth_enabled", lambda: True)
    monkeypatch.setattr(
        bakery_monitor,
        "claim_next_collection_job",
        AsyncMock(
            return_value=CollectionJobClaimResponse(
                available=True,
                job=CollectionJobResponse(
                    job_id="job-2",
                    monitor_uuid="monitor-1",
                    monitor_id="example/poundcake",
                    collector_type="ticket_context",
                    status="leased",
                    parameters={"req_id": "REQ-2"},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            )
        ),
    )
    monkeypatch.setattr(
        bakery_monitor,
        "run_collection_job",
        AsyncMock(side_effect=RuntimeError("collector boom")),
    )
    complete = AsyncMock(
        return_value=CollectionJobResponse(
            job_id="job-2",
            monitor_uuid="monitor-1",
            monitor_id="example/poundcake",
            collector_type="ticket_context",
            status="failed",
            error="collector boom",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr(bakery_monitor, "complete_collection_job", complete)

    response = await bakery_monitor.process_next_collection_job()

    assert response is not None
    assert response.status == "failed"
    assert complete.await_args.kwargs["status"] == "failed"
    assert complete.await_args.kwargs["error"] == "collector boom"

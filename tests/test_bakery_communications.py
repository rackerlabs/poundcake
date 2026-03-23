from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from api.services import bakery_client
from api.services.bakery_client import (
    BakeryTicketAccepted,
    BakeryTicketOperation,
    BakeryTicketResource,
)
from bakery.api import communications
from bakery.schemas import OperationAcceptedResponse, TicketCloseRequest, TicketCreateRequest
from shared.bakery_contract import (
    CommunicationAcceptedResponse,
    CommunicationNotifyRequest,
    CommunicationOperationResponse,
    CommunicationResponse,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self.text = "ok"
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _client_settings() -> SimpleNamespace:
    return SimpleNamespace(
        bakery_base_url="http://bakery.example",
        bakery_request_timeout_seconds=30,
        bakery_max_retries=1,
        bakery_auth_mode="none",
        bakery_poll_timeout_seconds=1,
        bakery_poll_interval_seconds=0,
    )


@pytest.mark.asyncio
async def test_open_communication_maps_ticket_create_response(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    create_ticket = AsyncMock(
        return_value=OperationAcceptedResponse(
            ticket_id="comm-1",
            operation_id="op-1",
            action="create",
            status="queued",
            created_at=now,
        )
    )
    monkeypatch.setattr(
        communications,
        "create_ticket",
        create_ticket,
    )

    response = await communications.open_communication(
        payload=communications.CommunicationOpenRequest(
            title="Disk alert",
            description="details",
            message="Manual attention may be required.",
            source="poundcake",
        ),
        idempotency_key="idem-1",
        db=None,
    )

    assert isinstance(response, CommunicationAcceptedResponse)
    assert response.communication_id == "comm-1"
    assert response.operation_id == "op-1"
    assert response.action == "create"
    sent_payload = create_ticket.await_args.kwargs["payload"]
    assert isinstance(sent_payload, TicketCreateRequest)
    assert sent_payload.message == "Manual attention may be required."
    assert sent_payload.source == "poundcake"


@pytest.mark.asyncio
async def test_close_communication_maps_managed_payload_fields(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    close_ticket = AsyncMock(
        return_value=OperationAcceptedResponse(
            ticket_id="comm-9",
            operation_id="op-9",
            action="close",
            status="queued",
            created_at=now,
        )
    )
    monkeypatch.setattr(communications, "close_ticket", close_ticket)

    response = await communications.close_communication(
        communication_id="comm-9",
        payload=communications.CommunicationCloseRequest(
            title="Alert resolved",
            description="PoundCake is closing this communication.",
            message="Alert resolved after successful auto-remediation.",
            source="poundcake",
            state="closed",
            context={"route_label": "Rackspace Core"},
        ),
        idempotency_key="idem-9",
        db=None,
    )

    assert response.communication_id == "comm-9"
    sent_payload = close_ticket.await_args.kwargs["payload"]
    assert isinstance(sent_payload, TicketCloseRequest)
    assert sent_payload.title == "Alert resolved"
    assert sent_payload.message == "Alert resolved after successful auto-remediation."
    assert sent_payload.source == "poundcake"


@pytest.mark.asyncio
async def test_notify_communication_maps_message_to_comment(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    add_comment = AsyncMock(
        return_value=OperationAcceptedResponse(
            ticket_id="comm-2",
            operation_id="op-2",
            action="comment",
            status="queued",
            created_at=now,
        )
    )
    monkeypatch.setattr(communications, "add_comment", add_comment)

    response = await communications.notify_communication(
        communication_id="comm-2",
        payload=CommunicationNotifyRequest(message="manual action required"),
        idempotency_key="idem-2",
        db=None,
    )

    assert response.communication_id == "comm-2"
    sent_payload = add_comment.await_args.kwargs["payload"]
    assert sent_payload.comment == "manual action required"


def test_communication_response_supports_agnostic_metadata() -> None:
    now = datetime.now(timezone.utc)
    payload = CommunicationResponse(
        communication_id="comm-3",
        provider_type="rackspace_core",
        provider_reference_id="240101-00001",
        state="open",
        latest_error=None,
        created_at=now,
        updated_at=now,
        data_source="local_cache",
        communication_data={"title": "Disk alert"},
        last_sync_operation_id="op-3",
        last_sync_at=now,
    )
    assert payload.communication_data == {"title": "Disk alert"}
    assert payload.provider_reference_id == "240101-00001"


@pytest.mark.asyncio
async def test_ticket_wrappers_normalize_communication_payloads(monkeypatch: pytest.MonkeyPatch):
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

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from api.services import bakery_client
from bakery.api import communications
from bakery.schemas import (
    CommunicationNotifyRequest,
    CommunicationResponse,
    OperationAcceptedResponse,
)


@pytest.mark.asyncio
async def test_open_communication_maps_ticket_create_response(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        communications,
        "create_ticket",
        AsyncMock(
            return_value=OperationAcceptedResponse(
                ticket_id="comm-1",
                operation_id="op-1",
                action="create",
                status="queued",
                created_at=now,
            )
        ),
    )

    response = await communications.open_communication(
        payload=communications.CommunicationOpenRequest(title="Disk alert", description="details"),
        idempotency_key="idem-1",
        db=None,
    )

    assert response.communication_id == "comm-1"
    assert response.operation_id == "op-1"
    assert response.action == "create"


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
        payload=CommunicationNotifyRequest(message="manual action required", has_bbcode=False),
        idempotency_key="idem-2",
        db=None,
    )

    assert response.communication_id == "comm-2"
    sent_payload = add_comment.await_args.kwargs["payload"]
    assert sent_payload.comment == "manual action required"
    assert sent_payload.has_bbcode is False


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
    monkeypatch.setattr(
        bakery_client,
        "open_communication_with_key",
        AsyncMock(return_value={"communication_id": "comm-4", "operation_id": "op-4"}),
    )
    monkeypatch.setattr(
        bakery_client,
        "get_communication",
        AsyncMock(
            return_value={
                "communication_id": "comm-4",
                "provider_reference_id": "INC0004",
                "state": "open",
                "communication_data": {"title": "Alert"},
            }
        ),
    )
    monkeypatch.setattr(
        bakery_client,
        "get_communication_operation",
        AsyncMock(
            return_value={
                "operation_id": "op-4",
                "communication_id": "comm-4",
                "status": "queued",
                "action": "open",
                "attempt_count": 0,
                "max_attempts": 5,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ),
    )

    accepted = await bakery_client.create_ticket_with_key(
        req_id="REQ-1",
        payload={"title": "A", "description": "B"},
        idempotency_key="idem-4",
    )
    ticket = await bakery_client.get_ticket("comm-4")
    operation = await bakery_client.get_operation("op-4")

    assert accepted["ticket_id"] == "comm-4"
    assert ticket["provider_ticket_id"] == "INC0004"
    assert ticket["ticket_data"] == {"title": "Alert"}
    assert operation["ticket_id"] == "comm-4"

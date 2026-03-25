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
from shared.bakery_contract import (
    CommunicationAcceptedResponse,
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
        bakery_base_url="https://bakery.example.com",
        bakery_request_timeout_seconds=30,
        bakery_max_retries=1,
        bakery_auth_mode="none",
        bakery_poll_timeout_seconds=1,
        bakery_poll_interval_seconds=0,
        bakery_hmac_key_id="",
        bakery_hmac_key="",
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

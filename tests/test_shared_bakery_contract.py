from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.bakery_contract import (
    CommunicationAcceptedResponse,
    CommunicationNotifyRequest,
    CommunicationOpenRequest,
)


def test_communication_open_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CommunicationOpenRequest.model_validate(
            {
                "title": "Disk alert",
                "description": "details",
                "unexpected": "boom",
            }
        )


def test_communication_notify_request_coalesces_message_and_comment() -> None:
    payload = CommunicationNotifyRequest.model_validate({"comment": "manual action required"})

    assert payload.message == "manual action required"
    assert payload.comment == "manual action required"


def test_communication_accepted_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CommunicationAcceptedResponse.model_validate(
            {
                "communication_id": "comm-1",
                "operation_id": "op-1",
                "action": "create",
                "status": "queued",
                "created_at": datetime.now(timezone.utc),
                "unexpected": "boom",
            }
        )

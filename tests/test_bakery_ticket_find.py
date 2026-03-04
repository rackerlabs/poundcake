from datetime import datetime, timezone
from pathlib import Path

from bakery.schemas import TicketResponse


def _tickets_source() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "bakery/api/tickets.py").read_text(encoding="utf-8")


def test_find_endpoint_queries_provider_search_when_not_dry_run() -> None:
    source = _tickets_source()
    assert '@router.post("/tickets/{ticket_id}/find", response_model=TicketResponse)' in source
    assert "if settings.ticketing_dry_run:" in source
    assert 'await mixer.process_request("search", search_payload)' in source


def test_ticket_response_supports_cached_ticket_data_metadata() -> None:
    now = datetime.now(timezone.utc)
    payload = TicketResponse(
        ticket_id="8f5e2dd8-42a2-4a57-b1dc-2dd14d4236fa",
        provider_type="rackspace_core",
        provider_ticket_id="240101-00001",
        state="open",
        latest_error=None,
        created_at=now,
        updated_at=now,
        data_source="local_cache",
        ticket_data={"title": "Disk alert"},
        last_sync_operation_id="0e8fcb26-95bd-4d77-93c4-b91978e47bd0",
        last_sync_at=now,
    )
    assert payload.data_source == "local_cache"
    assert payload.ticket_data == {"title": "Disk alert"}
    assert payload.last_sync_operation_id == "0e8fcb26-95bd-4d77-93c4-b91978e47bd0"

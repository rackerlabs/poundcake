from __future__ import annotations

import httpx
import pytest
from bakery.mixer.rackspace_core import RackspaceCoreMixer


@pytest.mark.asyncio
async def test_create_ticket_resolves_named_values_to_numeric_ids(monkeypatch: pytest.MonkeyPatch):
    mixer = RackspaceCoreMixer()
    calls: list[list[dict[str, object]]] = []

    async def _fake_execute(query_set: list[dict[str, object]]):
        calls.append(query_set)
        first = query_set[0]
        class_name = first.get("class")
        load_arg = first.get("load_arg")

        if class_name == "Ticket.Queue" and isinstance(load_arg, dict):
            return [{"result": [{"id": 472, "name": "CloudBuilders Support"}]}]

        if class_name == "Ticket.Queue" and load_arg == 472:
            return [
                {
                    "result": [
                        {
                            "id": 472,
                            "name": "CloudBuilders Support",
                            "subcategories": [[{"id": 29158, "name": "Monitoring"}]],
                            "sources": [{"id": 12, "name": "RunBook"}],
                            "severities": [
                                {"id": 1, "name": "Standard"},
                                {"id": 2, "name": "Urgent"},
                                {"id": 3, "name": "Emergency"},
                            ],
                        }
                    ]
                }
            ]

        if class_name == "Account.Account":
            assert first.get("args") == [472, 29158, 12, 2, "test subject", "test body"]
            return [{"result": {"load_value": "260309-12345"}}]

        raise AssertionError(f"Unexpected query_set: {query_set}")

    monkeypatch.setattr(mixer, "_execute_query", _fake_execute)

    result = await mixer._create_ticket(
        {
            "account_number": "10",
            "queue": "CloudBuilders Support",
            "subcategory": "Monitoring",
            "source": "poundcake",
            "severity": "warning",
            "subject": "test subject",
            "body": "test body",
        }
    )

    assert result["success"] is True
    assert result["ticket_id"] == "260309-12345"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_close_ticket_uses_set_status_by_name(monkeypatch: pytest.MonkeyPatch):
    mixer = RackspaceCoreMixer()
    calls: list[list[dict[str, object]]] = []

    async def _fake_execute(query_set: list[dict[str, object]]):
        calls.append(query_set)
        return [{"result": {"ok": True}}]

    monkeypatch.setattr(mixer, "_execute_query", _fake_execute)

    result = await mixer._close_ticket({"ticket_id": "260309-12345", "status": "confirmed_solved"})

    assert result["success"] is True
    assert calls[0][0]["method"] == "setStatusByName"
    assert calls[0][0]["args"] == ["Confirm Solved"]


@pytest.mark.asyncio
async def test_close_ticket_defaults_to_confirm_solved(monkeypatch: pytest.MonkeyPatch):
    mixer = RackspaceCoreMixer()
    calls: list[list[dict[str, object]]] = []

    async def _fake_execute(query_set: list[dict[str, object]]):
        calls.append(query_set)
        return [{"result": {"ok": True}}]

    monkeypatch.setattr(mixer, "_execute_query", _fake_execute)

    result = await mixer._close_ticket({"ticket_id": "260309-12345"})

    assert result["success"] is True
    assert calls[0][0]["args"] == ["Confirm Solved"]


@pytest.mark.asyncio
async def test_close_ticket_falls_back_to_set_attribute_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
):
    mixer = RackspaceCoreMixer()
    calls: list[list[dict[str, object]]] = []

    async def _fake_execute(query_set: list[dict[str, object]]):
        calls.append(query_set)
        if len(calls) == 1:
            request = httpx.Request("POST", "https://example.invalid/ctkapi/query/")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("boom", request=request, response=response)
        return [{"result": {"ok": True}}]

    monkeypatch.setattr(mixer, "_execute_query", _fake_execute)

    result = await mixer._close_ticket({"ticket_id": "260309-12345", "status": "Solved"})

    assert result["success"] is True
    assert calls[0][0]["method"] == "setStatusByName"
    assert "set_attribute" in calls[1][0]

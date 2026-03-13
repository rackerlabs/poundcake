from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bakery.mixer.github import GitHubMixer
from bakery.mixer.jira import JiraMixer
from bakery.mixer.pagerduty import PagerDutyMixer


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {}


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def patch(self, *args, **kwargs):
        return _Response()

    async def post(self, *args, **kwargs):
        return _Response()

    async def put(self, *args, **kwargs):
        return _Response()


@pytest.mark.asyncio
async def test_github_close_issue_adds_close_notes_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    mixer = GitHubMixer()
    add_comment = AsyncMock(return_value={"success": True, "ticket_id": "9"})
    monkeypatch.setattr(mixer, "_add_comment", add_comment)
    monkeypatch.setattr("bakery.mixer.github.httpx.AsyncClient", lambda *args, **kwargs: _Client())

    result = await mixer._close_issue(
        {
            "owner": "rackerlabs",
            "repo": "poundcake",
            "ticket_id": "9",
            "close_notes": "Resolved after recovery.",
        }
    )

    assert result["success"] is True
    add_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_jira_close_issue_adds_close_notes_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    mixer = JiraMixer()
    add_comment = AsyncMock(return_value={"success": True, "ticket_id": "OPS-9"})
    monkeypatch.setattr(mixer, "_add_comment", add_comment)
    monkeypatch.setattr("bakery.mixer.jira.httpx.AsyncClient", lambda *args, **kwargs: _Client())

    result = await mixer._close_issue(
        {
            "ticket_id": "OPS-9",
            "close_notes": {"type": "doc", "version": 1, "content": []},
        }
    )

    assert result["success"] is True
    add_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_pagerduty_close_incident_adds_close_note(monkeypatch: pytest.MonkeyPatch) -> None:
    mixer = PagerDutyMixer()
    add_note = AsyncMock(return_value={"success": True, "ticket_id": "PD-9"})
    monkeypatch.setattr(mixer, "_add_note", add_note)
    monkeypatch.setattr(
        "bakery.mixer.pagerduty.httpx.AsyncClient",
        lambda *args, **kwargs: _Client(),
    )

    result = await mixer._close_incident(
        {
            "ticket_id": "PD-9",
            "from_email": "alerts@example.com",
            "close_notes": "Resolved automatically.",
        }
    )

    assert result["success"] is True
    add_note.assert_awaited_once()

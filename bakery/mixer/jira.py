#!/usr/bin/env python3
"""Jira mixer for ticket management."""

from typing import Dict, Any
import httpx

from bakery.config import settings
from bakery.mixer.base import BaseMixer


class JiraMixer(BaseMixer):
    """Mixer for Jira ticketing system."""

    def __init__(self) -> None:
        """Initialize Jira mixer."""
        super().__init__()
        self.base_url = settings.jira_url
        self.username = settings.jira_username
        self.api_token = settings.jira_api_token
        self.timeout = settings.mixer_timeout_sec

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process Jira ticket request.

        Args:
            action: Action to perform (create, update, close, comment)
            data: Request data

        Returns:
            Response dictionary with success status and ticket details
        """
        if not self.base_url or not self.username or not self.api_token:
            return {
                "success": False,
                "error": "Jira credentials not configured",
            }

        try:
            if action == "create":
                return await self._create_issue(data)
            elif action == "update":
                return await self._update_issue(data)
            elif action == "close":
                return await self._close_issue(data)
            elif action == "comment":
                return await self._add_comment(data)
            elif action == "search":
                return await self._search_issues(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _create_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Jira issue."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                auth=(self.username, self.api_token),
                json={
                    "fields": {
                        "project": {"key": data.get("project_key")},
                        "summary": data.get("title", ""),
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": data.get("description", ""),
                                        }
                                    ],
                                }
                            ],
                        },
                        "issuetype": {"name": data.get("issue_type", "Task")},
                    }
                },
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "ticket_id": result["key"],
                "data": result,
            }

    async def _update_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing Jira issue."""
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            return {"success": False, "error": "ticket_id required for update"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(
                f"{self.base_url}/rest/api/3/issue/{ticket_id}",
                auth=(self.username, self.api_token),
                json={"fields": data.get("updates", {})},
            )
            response.raise_for_status()

            return {
                "success": True,
                "ticket_id": ticket_id,
            }

    async def _close_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Close a Jira issue."""
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            return {"success": False, "error": "ticket_id required for close"}

        # Transition to closed status (typically ID 2)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/issue/{ticket_id}/transitions",
                auth=(self.username, self.api_token),
                json={"transition": {"id": data.get("transition_id", "2")}},
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _add_comment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a comment to a Jira issue."""
        ticket_id = data.get("ticket_id")
        comment = data.get("comment")

        if not ticket_id or not comment:
            return {
                "success": False,
                "error": "ticket_id and comment required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/issue/{ticket_id}/comment",
                auth=(self.username, self.api_token),
                json={
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": comment}],
                            }
                        ],
                    }
                },
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _search_issues(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search Jira issues using JQL.

        Args:
            data: Search parameters:
                - jql: JQL query string (required)
                - limit: Max results to return (default 20)
                - offset: Starting offset for pagination (default 0)
                - fields: List of fields to return (optional)
        """
        jql = data.get("jql")
        if not jql:
            return {"success": False, "error": "jql required for search"}

        limit = data.get("limit", 20)
        offset = data.get("offset", 0)
        fields = data.get("fields")

        payload: Dict[str, Any] = {
            "jql": jql,
            "maxResults": limit,
            "startAt": offset,
        }
        if fields:
            payload["fields"] = fields

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/api/3/search",
                auth=(self.username, self.api_token),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "data": {
                    "results": result.get("issues", []),
                    "count": len(result.get("issues", [])),
                    "total": result.get("total", 0),
                },
            }

    async def validate_credentials(self) -> bool:
        """Validate Jira credentials."""
        if not self.base_url or not self.username or not self.api_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/rest/api/3/myself",
                    auth=(self.username, self.api_token),
                )
                return response.status_code == 200
        except Exception:
            return False

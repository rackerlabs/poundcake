#!/usr/bin/env python3
"""ServiceNow adapter for ticket management."""

from typing import Dict, Any
import httpx

from bakery.config import settings
from bakery.adapters.base import BaseAdapter


class ServiceNowAdapter(BaseAdapter):
    """Adapter for ServiceNow ticketing system."""

    def __init__(self) -> None:
        """Initialize ServiceNow adapter."""
        super().__init__()
        self.base_url = settings.servicenow_url
        self.username = settings.servicenow_username
        self.password = settings.servicenow_password
        self.timeout = settings.adapter_timeout_sec

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process ServiceNow ticket request.

        Args:
            action: Action to perform (create, update, close, comment)
            data: Request data

        Returns:
            Response dictionary with success status and ticket details
        """
        if not self.base_url or not self.username or not self.password:
            return {
                "success": False,
                "error": "ServiceNow credentials not configured",
            }

        try:
            if action == "create":
                return await self._create_incident(data)
            elif action == "update":
                return await self._update_incident(data)
            elif action == "close":
                return await self._close_incident(data)
            elif action == "comment":
                return await self._add_comment(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _create_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new ServiceNow incident."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/now/table/incident",
                auth=(self.username, self.password),
                json={
                    "short_description": data.get("title", ""),
                    "description": data.get("description", ""),
                    "urgency": data.get("urgency", "3"),
                    "impact": data.get("impact", "3"),
                },
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "ticket_id": result["result"]["number"],
                "data": result["result"],
            }

    async def _update_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing ServiceNow incident."""
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            return {"success": False, "error": "ticket_id required for update"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/api/now/table/incident/{ticket_id}",
                auth=(self.username, self.password),
                json=data.get("updates", {}),
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "ticket_id": ticket_id,
                "data": result["result"],
            }

    async def _close_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Close a ServiceNow incident."""
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            return {"success": False, "error": "ticket_id required for close"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/api/now/table/incident/{ticket_id}",
                auth=(self.username, self.password),
                json={
                    "state": "7",  # Closed
                    "close_notes": data.get("close_notes", "Closed by automation"),
                },
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _add_comment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a comment to a ServiceNow incident."""
        ticket_id = data.get("ticket_id")
        comment = data.get("comment")

        if not ticket_id or not comment:
            return {
                "success": False,
                "error": "ticket_id and comment required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/api/now/table/incident/{ticket_id}",
                auth=(self.username, self.password),
                json={"comments": comment},
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def validate_credentials(self) -> bool:
        """Validate ServiceNow credentials."""
        if not self.base_url or not self.username or not self.password:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/now/table/incident",
                    auth=(self.username, self.password),
                    params={"sysparm_limit": 1},
                )
                return response.status_code == 200
        except Exception:
            return False

#!/usr/bin/env python3
"""PagerDuty mixer for incident management."""

from typing import Dict, Any
import httpx

from bakery.config import settings
from bakery.mixer.base import BaseMixer


class PagerDutyMixer(BaseMixer):
    """Mixer for PagerDuty incident management."""

    def __init__(self) -> None:
        """Initialize PagerDuty mixer."""
        super().__init__()
        self.api_key = settings.pagerduty_api_key
        self.timeout = settings.mixer_timeout_sec
        self.base_url = "https://api.pagerduty.com"

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process PagerDuty incident request.

        Args:
            action: Action to perform (create, update, close, comment)
            data: Request data

        Returns:
            Response dictionary with success status and incident details
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "PagerDuty API key not configured",
            }

        try:
            if action == "create":
                return await self._create_incident(data)
            elif action == "update":
                return await self._update_incident(data)
            elif action == "close":
                return await self._close_incident(data)
            elif action == "comment":
                return await self._add_note(data)
            elif action == "search":
                return await self._search_incidents(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for PagerDuty API requests."""
        return {
            "Authorization": f"Token token={self.api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

    async def _create_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new PagerDuty incident."""
        service_id = data.get("service_id")
        from_email = data.get("from_email")

        if not service_id or not from_email:
            return {
                "success": False,
                "error": "service_id and from_email required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()
            headers["From"] = from_email

            response = await client.post(
                f"{self.base_url}/incidents",
                headers=headers,
                json={
                    "incident": {
                        "type": "incident",
                        "title": data.get("title", ""),
                        "service": {
                            "id": service_id,
                            "type": "service_reference",
                        },
                        "urgency": data.get("urgency", "high"),
                        "body": {
                            "type": "incident_body",
                            "details": data.get("description", ""),
                        },
                    }
                },
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "ticket_id": result["incident"]["id"],
                "data": result["incident"],
            }

    async def _update_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing PagerDuty incident."""
        ticket_id = data.get("ticket_id")
        from_email = data.get("from_email")

        if not ticket_id or not from_email:
            return {
                "success": False,
                "error": "ticket_id and from_email required for update",
            }

        update_data: Dict[str, Any] = {"type": "incident"}
        if "title" in data:
            update_data["title"] = data["title"]
        if "urgency" in data:
            update_data["urgency"] = data["urgency"]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()
            headers["From"] = from_email

            response = await client.put(
                f"{self.base_url}/incidents/{ticket_id}",
                headers=headers,
                json={"incident": update_data},
            )
            response.raise_for_status()

            return {
                "success": True,
                "ticket_id": ticket_id,
            }

    async def _close_incident(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Close a PagerDuty incident."""
        ticket_id = data.get("ticket_id")
        from_email = data.get("from_email")

        if not ticket_id or not from_email:
            return {
                "success": False,
                "error": "ticket_id and from_email required for close",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()
            headers["From"] = from_email

            response = await client.put(
                f"{self.base_url}/incidents/{ticket_id}",
                headers=headers,
                json={
                    "incident": {
                        "type": "incident",
                        "status": "resolved",
                    }
                },
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _add_note(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a note to a PagerDuty incident."""
        ticket_id = data.get("ticket_id")
        from_email = data.get("from_email")
        comment = data.get("comment")

        if not ticket_id or not from_email or not comment:
            return {
                "success": False,
                "error": "ticket_id, from_email, and comment required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = self._get_headers()
            headers["From"] = from_email

            response = await client.post(
                f"{self.base_url}/incidents/{ticket_id}/notes",
                headers=headers,
                json={
                    "note": {
                        "content": comment,
                    }
                },
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _search_incidents(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search PagerDuty incidents.

        Args:
            data: Search parameters:
                - statuses: List of statuses to filter by (optional)
                    e.g. ["triggered", "acknowledged", "resolved"]
                - service_ids: List of service IDs to filter by (optional)
                - since: Start date/time ISO string (optional)
                - until: End date/time ISO string (optional)
                - limit: Max results to return (default 20)
                - offset: Starting offset for pagination (default 0)
        """
        limit = data.get("limit", 20)
        offset = data.get("offset", 0)

        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        statuses = data.get("statuses")
        if statuses:
            params["statuses[]"] = statuses

        service_ids = data.get("service_ids")
        if service_ids:
            params["service_ids[]"] = service_ids

        since = data.get("since")
        if since:
            params["since"] = since

        until = data.get("until")
        if until:
            params["until"] = until

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/incidents",
                headers=self._get_headers(),
                params=params,
            )
            response.raise_for_status()
            result = response.json()

            incidents = result.get("incidents", [])
            total = result.get("total", len(incidents))

            return {
                "success": True,
                "data": {
                    "results": incidents,
                    "count": len(incidents),
                    "total": total,
                },
            }

    async def validate_credentials(self) -> bool:
        """Validate PagerDuty credentials."""
        if not self.api_key:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/users",
                    headers=self._get_headers(),
                    params={"limit": 1},
                )
                return response.status_code == 200
        except Exception:
            return False

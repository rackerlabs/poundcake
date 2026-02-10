#!/usr/bin/env python3
"""Rackspace Core mixer for ticket management via CTKAPI."""

from typing import Dict, Any, Optional, List
import httpx

from bakery.config import settings
from bakery.mixer.base import BaseMixer


class RackspaceCoreMixer(BaseMixer):
    """
    Mixer for Rackspace Core ticketing system.

    Uses the CTKAPI query endpoint to interact with Core tickets.
    Authentication is token-based via /ctkapi/login/{user_id}.
    All ticket operations go through the /ctkapi/query/ endpoint
    using CTK object query sets.
    """

    def __init__(self) -> None:
        """Initialize Rackspace Core mixer."""
        super().__init__()
        self.base_url = settings.rackspace_core_url
        self.username = settings.rackspace_core_username
        self.password = settings.rackspace_core_password
        self.timeout = settings.mixer_timeout_sec
        self._auth_token: Optional[str] = None

    async def process_request(
        self, action: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process Rackspace Core ticket request.

        Args:
            action: Action to perform (create, update, close, comment, search)
            data: Request data

        Returns:
            Response dictionary with success status and ticket details
        """
        if not self.base_url or not self.username or not self.password:
            return {
                "success": False,
                "error": "Rackspace Core credentials not configured",
            }

        try:
            if action == "create":
                return await self._create_ticket(data)
            elif action == "update":
                return await self._update_ticket(data)
            elif action == "close":
                return await self._close_ticket(data)
            elif action == "comment":
                return await self._add_comment(data)
            elif action == "search":
                return await self._search_tickets(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Authentication ──────────────────────────────────────────────

    async def _authenticate(
        self, client: httpx.AsyncClient
    ) -> str:
        """
        Authenticate with CTKAPI and return auth token.

        Posts password to /ctkapi/login/{username} and extracts the
        authtoken from the response.
        """
        response = await client.post(
            f"{self.base_url}/ctkapi/login/{self.username}",
            content=self.password,
            headers={"Content-Type": "text/plain"},
        )
        response.raise_for_status()
        result = response.json()
        token = result.get("authtoken")
        if not token:
            raise ValueError("Authentication failed: no authtoken in response")
        self._auth_token = token
        return token

    def _get_headers(self) -> Dict[str, str]:
        """Return headers with current auth token."""
        return {
            "X-Auth": self._auth_token or "",
            "Content-Type": "application/json",
        }

    # ── Core query executor with 401 retry ──────────────────────────

    async def _execute_query(
        self,
        query_set: List[Dict[str, Any]],
    ) -> Any:
        """
        Execute a CTKAPI query set against /ctkapi/query/.

        Handles authentication transparently:
        - Authenticates if no token is cached
        - On 401, re-authenticates once and retries

        Args:
            query_set: List of CTK query objects to execute

        Returns:
            Parsed JSON response from CTKAPI
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Ensure we have a token
            if not self._auth_token:
                await self._authenticate(client)

            # First attempt
            response = await client.post(
                f"{self.base_url}/ctkapi/query/",
                headers=self._get_headers(),
                json=query_set,
            )

            # Retry once on 401
            if response.status_code == 401:
                await self._authenticate(client)
                response = await client.post(
                    f"{self.base_url}/ctkapi/query/",
                    headers=self._get_headers(),
                    json=query_set,
                )

            response.raise_for_status()
            return response.json()

    # ── Ticket Actions ──────────────────────────────────────────────

    async def _create_ticket(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new Rackspace Core ticket.

        Uses Account.Account.addTicket method via the query API.

        Required data fields:
            - account_number: Rackspace account number
            - queue: Ticket queue name
            - subcategory: Ticket subcategory
            - subject: Ticket subject line
            - body: Ticket body/description

        Optional data fields:
            - source: Ticket source (default "Bakery")
            - severity: Ticket severity (default "Normal")
        """
        account_number = data.get("account_number")
        queue = data.get("queue")
        subcategory = data.get("subcategory")
        subject = data.get("subject")
        body = data.get("body")

        if not all([account_number, queue, subcategory, subject, body]):
            return {
                "success": False,
                "error": (
                    "account_number, queue, subcategory, subject, "
                    "and body are required for create"
                ),
            }

        source = data.get("source", "Bakery")
        severity = data.get("severity", "Normal")

        query_set = [
            {
                "class": "Account.Account",
                "load_arg": str(account_number),
                "action": "method",
                "method": "addTicket",
                "args": [queue, subcategory, source, severity, subject, body],
            }
        ]

        result = await self._execute_query(query_set)

        # addTicket returns the new ticket number in the result
        ticket_number = None
        if isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, dict):
                ticket_number = str(
                    first.get("ticket_number")
                    or first.get("result")
                    or first.get("id")
                    or ""
                )

        return {
            "success": True,
            "ticket_id": ticket_number or "",
            "data": result,
        }

    async def _update_ticket(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing Rackspace Core ticket.

        Uses Ticket.Ticket set_attribute action to update fields.

        Required data fields:
            - ticket_number: CORE ticket number
            - attributes: Dict of attribute name -> value to set
        """
        ticket_number = data.get("ticket_number") or data.get("ticket_id")
        attributes = data.get("attributes")

        if not ticket_number:
            return {
                "success": False,
                "error": "ticket_number required for update",
            }
        if not attributes or not isinstance(attributes, dict):
            return {
                "success": False,
                "error": "attributes dict required for update",
            }

        query_set = [
            {
                "class": "Ticket.Ticket",
                "load_arg": str(ticket_number),
                "action": "set_attribute",
                "attribute": attr_name,
                "value": attr_value,
            }
            for attr_name, attr_value in attributes.items()
        ]

        result = await self._execute_query(query_set)

        return {
            "success": True,
            "ticket_id": str(ticket_number),
            "data": result,
        }

    async def _close_ticket(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Close a Rackspace Core ticket.

        Sets the ticket status to closed via set_attribute.

        Required data fields:
            - ticket_number: CORE ticket number

        Optional data fields:
            - status: CTK status value (default "Solved")
        """
        ticket_number = data.get("ticket_number") or data.get("ticket_id")
        if not ticket_number:
            return {
                "success": False,
                "error": "ticket_number required for close",
            }

        status_value = data.get("status", "Solved")

        query_set = [
            {
                "class": "Ticket.Ticket",
                "load_arg": str(ticket_number),
                "action": "set_attribute",
                "attribute": "status",
                "value": status_value,
            }
        ]

        result = await self._execute_query(query_set)

        return {
            "success": True,
            "ticket_id": str(ticket_number),
            "data": result,
        }

    async def _add_comment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a comment to a Rackspace Core ticket.

        Uses Ticket.Ticket method call to add a comment.

        Required data fields:
            - ticket_number: CORE ticket number
            - comment: Comment text to add
        """
        ticket_number = data.get("ticket_number") or data.get("ticket_id")
        comment = data.get("comment")

        if not ticket_number or not comment:
            return {
                "success": False,
                "error": "ticket_number and comment required",
            }

        query_set = [
            {
                "class": "Ticket.Ticket",
                "load_arg": str(ticket_number),
                "action": "method",
                "method": "addComment",
                "args": [comment],
            }
        ]

        result = await self._execute_query(query_set)

        return {
            "success": True,
            "ticket_id": str(ticket_number),
            "data": result,
        }

    async def _search_tickets(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search for Rackspace Core tickets.

        Supports three search modes:

        1. Direct lookup by ticket number:
            - ticket_number: CORE ticket number
            - attributes: List of attribute names to return (optional)

        2. Where-condition search:
            - where_conditions: List of dicts with {field, op, value}
            - attributes: List of attribute names to return (optional)

        3. Queue-based search:
            - queue_label: Queue label to load view for
            - attributes: List of attribute names to return (optional)
        """
        ticket_number = data.get("ticket_number")
        where_conditions = data.get("where_conditions")
        queue_label = data.get("queue_label")
        attributes = data.get("attributes", [
            "ticket_number", "subject", "status", "queue", "created_date",
        ])

        if ticket_number:
            # Mode 1: Direct ticket lookup
            query_set = [
                {
                    "class": "Ticket.Ticket",
                    "load_arg": str(ticket_number),
                    "action": "attributes",
                    "attributes": attributes,
                }
            ]
        elif where_conditions:
            # Mode 2: Where-condition search via TicketWhere
            where_list = []
            for cond in where_conditions:
                where_list.append({
                    "field": cond["field"],
                    "op": cond.get("op", "eq"),
                    "value": cond["value"],
                })

            query_set = [
                {
                    "class": "Ticket.TicketWhere",
                    "action": "attributes",
                    "attributes": attributes,
                    "where": where_list,
                }
            ]
        elif queue_label:
            # Mode 3: Queue-based ticket loading
            query_set = [
                {
                    "class": "Ticket.Ticket",
                    "action": "method",
                    "method": "loadQueueView",
                    "args": [queue_label],
                }
            ]
        else:
            return {
                "success": False,
                "error": (
                    "search requires one of: ticket_number, "
                    "where_conditions, or queue_label"
                ),
            }

        result = await self._execute_query(query_set)

        # Normalize result into a list
        results: List[Dict[str, Any]] = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    inner = item.get("result", item)
                    if isinstance(inner, list):
                        results.extend(inner)
                    else:
                        results.append(inner)
                elif isinstance(item, list):
                    results.extend(item)

        return {
            "success": True,
            "data": {
                "results": results,
                "count": len(results),
                "total": len(results),
            },
        }

    # ── Credential Validation ───────────────────────────────────────

    async def validate_credentials(self) -> bool:
        """
        Validate Rackspace Core credentials.

        Authenticates and then checks the session validity via
        /ctkapi/session/{token}.
        """
        if not self.base_url or not self.username or not self.password:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                token = await self._authenticate(client)
                response = await client.get(
                    f"{self.base_url}/ctkapi/session/{token}",
                    headers=self._get_headers(),
                )
                if response.status_code != 200:
                    return False
                result = response.json()
                return result.get("valid", False) is True
        except Exception:
            return False

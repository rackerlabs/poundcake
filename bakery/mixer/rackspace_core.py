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
        self.verify_ssl = settings.rackspace_core_verify_ssl
        self._auth_token: Optional[str] = None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                return int(text)
        return None

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _extract_result_rows(self, result: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not isinstance(result, list):
            return rows
        for item in result:
            if not isinstance(item, dict):
                continue
            inner = item.get("result", item)
            if isinstance(inner, dict):
                rows.append(inner)
            elif isinstance(inner, list):
                for row in inner:
                    if isinstance(row, dict):
                        rows.append(row)
        return rows

    def _flatten_value_rows(self, value: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                if "id" in node and "name" in node:
                    rows.append(node)
                for nested in node.values():
                    _walk(nested)
            elif isinstance(node, list):
                for nested in node:
                    _walk(nested)

        _walk(value)

        deduped: List[Dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for row in rows:
            row_id = self._coerce_int(row.get("id"))
            row_name = self._normalize_text(row.get("name"))
            if row_id is None or not row_name:
                continue
            key = (row_id, row_name.casefold())
            if key in seen:
                continue
            seen.add(key)
            deduped.append({"id": row_id, "name": row_name})
        return deduped

    def _pick_named_value_id(self, rows: List[Dict[str, Any]], desired: Any) -> int | None:
        desired_id = self._coerce_int(desired)
        if desired_id is not None:
            return desired_id

        desired_name = self._normalize_text(desired)
        if not desired_name:
            return None
        desired_key = desired_name.casefold()

        for row in rows:
            row_name = self._normalize_text(row.get("name"))
            if row_name.casefold() == desired_key:
                row_id = self._coerce_int(row.get("id"))
                if row_id is not None:
                    return row_id
        return None

    async def _resolve_queue_id(self, queue: Any) -> int | None:
        queue_id = self._coerce_int(queue)
        if queue_id is not None:
            return queue_id

        queue_name = self._normalize_text(queue)
        if not queue_name:
            return None

        lookup_variants = [
            ["name", "=", queue_name],
            ["name", "LIKE", f"%{queue_name}%"],
        ]
        for condition in lookup_variants:
            query_set = [
                {
                    "class": "Ticket.Queue",
                    "load_arg": {
                        "class": "Ticket.QueueWhere",
                        "values": [condition],
                    },
                    "attributes": ["id", "name"],
                }
            ]
            result = await self._execute_query(query_set)
            rows = self._extract_result_rows(result)
            if not rows:
                continue

            queue_key = queue_name.casefold()
            for row in rows:
                row_name = self._normalize_text(row.get("name"))
                if row_name.casefold() == queue_key:
                    match_id = self._coerce_int(row.get("id"))
                    if match_id is not None:
                        return match_id

            first_id = self._coerce_int(rows[0].get("id"))
            if first_id is not None:
                return first_id

        return None

    async def _load_queue_taxonomy(self, queue_id: int) -> Dict[str, List[Dict[str, Any]]]:
        query_set = [
            {
                "class": "Ticket.Queue",
                "load_arg": queue_id,
                "attributes": ["id", "name", "subcategories", "sources", "severities"],
            }
        ]
        result = await self._execute_query(query_set)
        rows = self._extract_result_rows(result)
        if not rows:
            return {"subcategories": [], "sources": [], "severities": []}
        queue_row = rows[0]
        return {
            "subcategories": self._flatten_value_rows(queue_row.get("subcategories")),
            "sources": self._flatten_value_rows(queue_row.get("sources")),
            "severities": self._flatten_value_rows(queue_row.get("severities")),
        }

    @staticmethod
    def _normalize_source_name(source: Any) -> str:
        source_text = str(source or "").strip()
        if not source_text:
            return "RunBook"
        if source_text.casefold() in {"poundcake", "poundcake-codex", "bakery", "automation"}:
            return "RunBook"
        return source_text

    @staticmethod
    def _normalize_severity_name(severity: Any) -> str:
        severity_text = str(severity or "").strip()
        if not severity_text:
            return "Standard"
        mapped = {
            "info": "Standard",
            "low": "Standard",
            "normal": "Standard",
            "standard": "Standard",
            "warning": "Urgent",
            "high": "Urgent",
            "urgent": "Urgent",
            "critical": "Emergency",
            "emergency": "Emergency",
        }
        return mapped.get(severity_text.casefold(), severity_text)

    @staticmethod
    def _normalize_status_name(status_value: Any) -> str:
        raw = str(status_value or "").strip().replace("_", " ")
        if not raw:
            return "Solved"
        lowered = raw.casefold()
        if lowered in {"confirm solved", "confirmed solved"}:
            return "Confirm Solved"
        if lowered == "solved":
            return "Solved"
        if lowered == "closed":
            return "Closed"
        return " ".join(part.capitalize() for part in raw.split())

    async def _resolve_create_classification_ids(
        self,
        *,
        queue: Any,
        subcategory: Any,
        source: Any,
        severity: Any,
    ) -> tuple[int, int, int, int] | None:
        queue_id = await self._resolve_queue_id(queue)
        if queue_id is None:
            return None

        taxonomy = await self._load_queue_taxonomy(queue_id)
        subcategory_rows = taxonomy.get("subcategories", [])
        source_rows = taxonomy.get("sources", [])
        severity_rows = taxonomy.get("severities", [])

        subcategory_id = self._pick_named_value_id(subcategory_rows, subcategory)
        if subcategory_id is None:
            subcategory_id = self._pick_named_value_id(
                subcategory_rows, settings.rackspace_core_default_subcategory
            )
        if subcategory_id is None and subcategory_rows:
            subcategory_id = self._coerce_int(subcategory_rows[0].get("id"))

        source_id = self._pick_named_value_id(source_rows, self._normalize_source_name(source))
        if source_id is None:
            source_id = self._pick_named_value_id(source_rows, "RunBook")
        if source_id is None and source_rows:
            source_id = self._coerce_int(source_rows[0].get("id"))

        severity_id = self._pick_named_value_id(
            severity_rows, self._normalize_severity_name(severity)
        )
        if severity_id is None:
            severity_id = self._pick_named_value_id(severity_rows, "Standard")
        if severity_id is None and severity_rows:
            severity_id = self._coerce_int(severity_rows[0].get("id"))

        if queue_id is None or subcategory_id is None or source_id is None or severity_id is None:
            return None
        return queue_id, subcategory_id, source_id, severity_id

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
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

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """
        Authenticate with CTKAPI and return auth token.

        Posts password to /ctkapi/login/{username} and extracts the
        authtoken from the response.
        """
        response = await client.post(
            f"{self.base_url}/ctkapi/login/{self.username}",
            json={"password": self.password},
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
        async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
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
            - source: Ticket source name (for example "RunBook")
            - severity: Ticket severity name (for example "Standard", "Urgent")
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

        source = data.get("source")
        severity = data.get("severity")
        has_bbcode = bool(data.get("has_bbcode", True))
        classification_ids = await self._resolve_create_classification_ids(
            queue=queue,
            subcategory=subcategory,
            source=source,
            severity=severity,
        )
        if classification_ids is None:
            return {
                "success": False,
                "error": (
                    "Unable to resolve Rackspace Core queue/subcategory/source/severity IDs "
                    "from provided values."
                ),
            }
        queue_id, subcategory_id, source_id, severity_id = classification_ids

        query_set = [
            {
                "class": "Account.Account",
                "load_arg": str(account_number),
                "method": "addTicket",
                "args": [queue_id, subcategory_id, source_id, severity_id, subject, body],
                "keyword_args": {
                    "has_bbcode": has_bbcode,
                },
                "result_map": {
                    "number": "number",
                    "status": "status.id",
                    "account": "account.number",
                },
            }
        ]

        result = await self._execute_query(query_set)

        # addTicket returns the new ticket number in the result
        ticket_number = None
        if isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, dict):
                result_obj = first.get("result")
                if isinstance(result_obj, dict):
                    ticket_number = str(
                        result_obj.get("number")
                        or result_obj.get("ticket_number")
                        or result_obj.get("id")
                        or result_obj.get("load_value")
                        or ""
                    )
                elif result_obj:
                    ticket_number = str(result_obj)
                else:
                    ticket_number = str(
                        first.get("ticket_number")
                        or first.get("id")
                        or first.get("load_value")
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
                "set_attribute": attributes,
            }
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

        status_value = self._normalize_status_name(data.get("status", "Solved"))

        query_set = [
            {
                "class": "Ticket.Ticket",
                "load_arg": str(ticket_number),
                "method": "setStatusByName",
                "args": [status_value],
            }
        ]

        try:
            result = await self._execute_query(query_set)
        except httpx.HTTPStatusError:
            # Compatibility fallback for environments that still permit direct status mutation.
            fallback_query_set = [
                {
                    "class": "Ticket.Ticket",
                    "load_arg": str(ticket_number),
                    "set_attribute": {
                        "status": status_value,
                    },
                }
            ]
            result = await self._execute_query(fallback_query_set)

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
                "method": "addComment",
                "args": [comment],
                "keyword_args": {
                    "has_bbcode": bool(data.get("has_bbcode", True)),
                },
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
        attributes = data.get(
            "attributes",
            [
                "ticket_number",
                "subject",
                "status",
                "queue",
                "created_date",
            ],
        )

        if ticket_number:
            # Mode 1: Direct ticket lookup
            query_set = [
                {
                    "class": "Ticket.Ticket",
                    "load_arg": str(ticket_number),
                    "attributes": attributes,
                }
            ]
        elif where_conditions:
            # Mode 2: Where-condition search via TicketWhere
            values: List[Any] = []
            for idx, cond in enumerate(where_conditions):
                if isinstance(cond, dict):
                    field = cond["field"]
                    op = cond.get("op", "=")
                    value = cond["value"]
                    values.append([field, op, value])
                elif isinstance(cond, list) and len(cond) == 3:
                    values.append(cond)
                else:
                    raise ValueError(
                        "where_conditions entries must be dicts with "
                        "{field, op, value} or 3-item arrays"
                    )

                if idx < len(where_conditions) - 1:
                    values.append("&")

            query_set = [
                {
                    "class": "Ticket.Ticket",
                    "load_arg": {
                        "class": "Ticket.TicketWhere",
                        "values": values,
                    },
                    "attributes": attributes,
                }
            ]
        elif queue_label:
            # Mode 3: Queue-based ticket loading
            query_set = [
                {
                    "class": "Ticket.Ticket",
                    "load_method": "loadQueueView",
                    "load_arg": {
                        "label": queue_label,
                    },
                    "attributes": attributes,
                }
            ]
        else:
            return {
                "success": False,
                "error": (
                    "search requires one of: ticket_number, " "where_conditions, or queue_label"
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
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
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

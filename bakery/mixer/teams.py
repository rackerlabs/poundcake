#!/usr/bin/env python3
"""Microsoft Teams webhook mixer."""

from __future__ import annotations

from typing import Any, Dict

import httpx

from bakery.config import settings
from bakery.mixer.base import BaseMixer


class TeamsMixer(BaseMixer):
    def __init__(self) -> None:
        super().__init__()
        self.webhook_url = settings.teams_webhook_url
        self.timeout = settings.mixer_timeout_sec

    @staticmethod
    def _message(data: Dict[str, Any]) -> str:
        for key in ("message", "comment", "description", "title"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "PoundCake communication update."

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.webhook_url:
            return {"success": False, "error": "Teams webhook URL not configured"}
        if action == "search":
            return {"success": False, "error": "Teams mixer does not support search"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.webhook_url, json={"text": self._message(data)})
            response.raise_for_status()
        return {"success": True, "ticket_id": str(data.get("ticket_id") or "teams-message")}

    async def validate_credentials(self) -> bool:
        return bool(self.webhook_url)

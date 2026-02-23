#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""HTTP client for PoundCake API."""

from typing import Any, Optional, cast

from api.core.http_client import request_with_retry_sync


class PoundCakeClient:
    """Client for interacting with PoundCake API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make an HTTP request to the API and decode JSON when available."""
        url = f"{self.base_url}{path}"
        response = request_with_retry_sync(
            method=method,
            url=url,
            headers=self.headers,
            json=json,
            params=params,
            timeout=30.0,
        )
        response.raise_for_status()

        if not response.content:
            return {}
        if "application/json" in (response.headers.get("content-type") or ""):
            return response.json()
        return response.text

    # Order management
    def list_orders(
        self,
        processing_status: Optional[str] = None,
        alert_status: Optional[str] = None,
        alert_group_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List orders with optional filters."""
        params: dict[str, Any] = {}
        if processing_status:
            params["processing_status"] = processing_status
        if alert_status:
            params["alert_status"] = alert_status
        if alert_group_name:
            params["alert_group_name"] = alert_group_name
        payload = self._request("GET", "/api/v1/orders", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise ValueError("Unexpected orders response format")

    def get_order(self, order_id: int) -> dict[str, Any]:
        """Get a specific order by ID."""
        payload = self._request("GET", f"/api/v1/orders/{order_id}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected order response format")

    # Prometheus rule management
    def list_rules(self) -> list[dict[str, Any]]:
        """List all Prometheus rules."""
        payload = self._request("GET", "/api/v1/prometheus/rules")
        if isinstance(payload, dict) and isinstance(payload.get("rules"), list):
            return cast(list[dict[str, Any]], payload["rules"])
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise ValueError("Unexpected rule list response format")

    def get_rule(self, source_name: str, group_name: str, rule_name: str) -> dict[str, Any]:
        """Resolve a specific rule from the current rule list."""
        for rule in self.list_rules():
            source = str(rule.get("crd") or rule.get("file") or "")
            if source != source_name:
                continue
            if str(rule.get("group") or "") != group_name:
                continue
            if str(rule.get("name") or "") != rule_name:
                continue
            return rule
        raise ValueError(
            f"Rule not found: source={source_name!r}, group={group_name!r}, rule={rule_name!r}"
        )

    def create_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new Prometheus rule."""
        payload = self._request(
            "POST",
            "/api/v1/prometheus/rules",
            json=rule_data,
            params={
                "rule_name": rule_name,
                "group_name": group_name,
                "file_name": source_name,
            },
        )
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected create rule response format")

    def update_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing Prometheus rule."""
        payload = self._request(
            "PUT",
            f"/api/v1/prometheus/rules/{rule_name}",
            json=rule_data,
            params={
                "group_name": group_name,
                "file_name": source_name,
            },
        )
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected update rule response format")

    def delete_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
    ) -> dict[str, Any]:
        """Delete a Prometheus rule."""
        payload = self._request(
            "DELETE",
            f"/api/v1/prometheus/rules/{rule_name}",
            params={
                "group_name": group_name,
                "file_name": source_name,
            },
        )
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected delete rule response format")

    # Legacy API compatibility stubs
    def list_mappings(self) -> dict[str, Any]:
        raise NotImplementedError("Mappings endpoints are not available in the current API")

    def get_mapping(self, alert_name: str) -> dict[str, Any]:
        raise NotImplementedError("Mappings endpoints are not available in the current API")

    # StackStorm action management
    def list_st2_actions(
        self,
        pack: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List StackStorm actions via /api/v1/cook/actions."""
        params: dict[str, Any] = {"limit": limit}
        if pack:
            params["pack"] = pack
        payload = self._request("GET", "/api/v1/cook/actions", params=params)
        if isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            return cast(list[dict[str, Any]], payload["actions"])
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise ValueError("Unexpected actions response format")

    def get_st2_action(self, action_ref: str) -> dict[str, Any]:
        """Get a specific StackStorm action."""
        payload = self._request("GET", f"/api/v1/cook/actions/{action_ref}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected action response format")

    # Health checks
    def health(self) -> dict[str, Any]:
        """Check API health."""
        payload = self._request("GET", "/api/v1/health")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise ValueError("Unexpected health response format")

    def ready(self) -> dict[str, Any]:
        """Alias for health check (legacy compatibility)."""
        return self.health()

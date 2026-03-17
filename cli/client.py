"""HTTP client for the PoundCake CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, cast

import httpx

from api.core.http_client import request_with_retry_sync
from cli.session import SessionStore, StoredSession


class PoundCakeClientError(RuntimeError):
    """Base exception for CLI client failures."""


class NotFoundError(PoundCakeClientError):
    """Raised when a requested resource cannot be found."""


@dataclass
class LoginResult:
    """Structured login result returned by the auth endpoint."""

    session_id: str
    username: str
    expires_at: str
    provider: str
    role: str
    display_name: str | None = None
    is_superuser: bool = False
    permissions: list[str] | None = None
    token_type: str = "Bearer"


@dataclass
class ProviderInfo:
    """Enabled auth provider metadata."""

    name: str
    label: str
    login_mode: str
    cli_login_mode: str
    browser_login: bool = False
    device_login: bool = False
    password_login: bool = False


@dataclass
class AuthMeResult:
    """Current principal metadata."""

    username: str
    display_name: str | None
    provider: str
    role: str
    principal_type: str
    principal_id: int | None
    is_superuser: bool
    permissions: list[str]
    groups: list[str]
    expires_at: str | None = None


@dataclass
class DeviceAuthorizationStart:
    """CLI device authorization bootstrap payload."""

    provider: str
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


class PoundCakeClient:
    """Client for interacting with the PoundCake API."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        *,
        session_store: SessionStore | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_store = session_store or SessionStore()
        self.session = None if api_key else self.session_store.get(self.base_url)
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def _cookies(self, *, use_session: bool = True) -> dict[str, str] | None:
        if self.api_key or not use_session or not self.session:
            return None
        return {"session_token": self.session.session_id}

    def _extract_error_detail(self, response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = response.json()
            except ValueError:
                data = None
            if isinstance(data, dict) and "detail" in data:
                detail = data["detail"]
                if isinstance(detail, dict):
                    return str(detail)
                return str(detail)
        text = response.text.strip()
        if text:
            return text
        return response.reason_phrase or f"HTTP {response.status_code}"

    def _decode_body(self, response: httpx.Response) -> Any:
        if not response.content:
            return {}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        use_session: bool = True,
    ) -> Any:
        url = f"{self.base_url}{path}"
        response = request_with_retry_sync(
            method=method,
            url=url,
            headers=self.headers,
            json=json,
            params=params,
            cookies=self._cookies(use_session=use_session),
            timeout=30.0,
        )
        if response.status_code == 401 and self.session and not self.api_key:
            self.clear_session()
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_detail(response)
            if response.status_code == 404:
                raise NotFoundError(message) from exc
            raise PoundCakeClientError(message) from exc
        return self._decode_body(response)

    def clear_session(self) -> None:
        """Remove any stored session for this base URL."""
        self.session_store.delete(self.base_url)
        self.session = None

    def _store_login_payload(self, payload: Any) -> LoginResult:
        if not isinstance(payload, dict):
            raise PoundCakeClientError("Unexpected login response format")
        result = LoginResult(
            session_id=str(payload["session_id"]),
            username=str(payload["username"]),
            expires_at=str(payload["expires_at"]),
            provider=str(payload["provider"]),
            role=str(payload["role"]),
            display_name=(
                None if payload.get("display_name") is None else str(payload.get("display_name"))
            ),
            is_superuser=bool(payload.get("is_superuser")),
            permissions=[str(item) for item in payload.get("permissions") or []] or None,
            token_type=str(payload.get("token_type") or "Bearer"),
        )
        session = StoredSession(
            session_id=result.session_id,
            username=result.username,
            expires_at=result.expires_at,
            provider=result.provider,
            role=result.role,
            display_name=result.display_name,
            is_superuser=result.is_superuser,
            permissions=result.permissions,
        )
        self.session_store.save(self.base_url, session)
        self.session = session
        return result

    def login(self, provider: str, username: str, password: str) -> LoginResult:
        """Authenticate with username/password and persist the session locally."""
        payload = self._request(
            "POST",
            "/api/v1/auth/login",
            json={"provider": provider, "username": username, "password": password},
            use_session=False,
        )
        return self._store_login_payload(payload)

    def logout(self) -> bool:
        """Attempt remote logout when a session exists, then clear the local session."""
        had_session = self.session is not None
        if self.session and not self.api_key:
            try:
                self._request("POST", "/api/v1/auth/logout")
            except PoundCakeClientError:
                pass
        self.clear_session()
        return had_session

    def get_settings(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/settings")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected settings response format")

    def get_auth_providers(self) -> list[ProviderInfo]:
        payload = self._request("GET", "/api/v1/auth/providers", use_session=False)
        if not isinstance(payload, list):
            raise PoundCakeClientError("Unexpected auth providers response format")
        return [
            ProviderInfo(
                name=str(item["name"]),
                label=str(item["label"]),
                login_mode=str(item["login_mode"]),
                cli_login_mode=str(item["cli_login_mode"]),
                browser_login=bool(item.get("browser_login")),
                device_login=bool(item.get("device_login")),
                password_login=bool(item.get("password_login")),
            )
            for item in payload
            if isinstance(item, dict)
        ]

    def auth_me(self) -> AuthMeResult:
        payload = self._request("GET", "/api/v1/auth/me")
        if not isinstance(payload, dict):
            raise PoundCakeClientError("Unexpected auth me response format")
        return AuthMeResult(
            username=str(payload["username"]),
            display_name=(
                None if payload.get("display_name") is None else str(payload.get("display_name"))
            ),
            provider=str(payload["provider"]),
            role=str(payload["role"]),
            principal_type=str(payload["principal_type"]),
            principal_id=(int(payload["principal_id"]) if payload.get("principal_id") else None),
            is_superuser=bool(payload.get("is_superuser")),
            permissions=[str(item) for item in payload.get("permissions") or []],
            groups=[str(item) for item in payload.get("groups") or []],
            expires_at=(
                None if payload.get("expires_at") is None else str(payload.get("expires_at"))
            ),
        )

    def start_device_login(self, provider: str) -> DeviceAuthorizationStart:
        payload = self._request(
            "POST",
            "/api/v1/auth/device/start",
            json={"provider": provider},
            use_session=False,
        )
        if not isinstance(payload, dict):
            raise PoundCakeClientError("Unexpected device authorization response format")
        return DeviceAuthorizationStart(
            provider=str(payload.get("provider") or provider),
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            verification_uri_complete=(
                None
                if payload.get("verification_uri_complete") is None
                else str(payload.get("verification_uri_complete"))
            ),
            expires_in=int(payload.get("expires_in") or 0),
            interval=int(payload.get("interval") or 5),
        )

    def poll_device_login(self, provider: str, device_code: str) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/api/v1/auth/device/poll",
            json={"provider": provider, "device_code": device_code},
            use_session=False,
        )
        if isinstance(payload, dict):
            session = payload.get("session")
            if isinstance(session, dict):
                self._store_login_payload(session)
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected device poll response format")

    def list_auth_principals(
        self,
        *,
        provider: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if provider:
            params["provider"] = provider
        if search:
            params["search"] = search
        payload = self._request("GET", "/api/v1/auth/principals", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected auth principals response format")

    def list_auth_bindings(self, *, provider: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] | None = None
        if provider:
            params = {"provider": provider}
        payload = self._request("GET", "/api/v1/auth/bindings", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected auth bindings response format")

    def create_auth_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/auth/bindings", json=payload)
        if isinstance(result, dict):
            return cast(dict[str, Any], result)
        raise PoundCakeClientError("Unexpected auth binding response format")

    def update_auth_binding(self, binding_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("PATCH", f"/api/v1/auth/bindings/{binding_id}", json=payload)
        if isinstance(result, dict):
            return cast(dict[str, Any], result)
        raise PoundCakeClientError("Unexpected auth binding response format")

    def delete_auth_binding(self, binding_id: int) -> dict[str, Any]:
        result = self._request("DELETE", f"/api/v1/auth/bindings/{binding_id}")
        if isinstance(result, dict):
            return cast(dict[str, Any], result)
        raise PoundCakeClientError("Unexpected auth binding delete response format")

    # Health and overview
    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/health")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected health response format")

    def ready(self) -> dict[str, Any]:
        return self.health()

    def stats(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/stats")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected stats response format")

    def observability_overview(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/observability/overview")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected observability overview response format")

    def list_observability_activity(
        self,
        *,
        activity_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if activity_type:
            params["type"] = activity_type
        payload = self._request("GET", "/api/v1/observability/activity", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected observability activity response format")

    # Incidents / orders
    def list_orders(
        self,
        *,
        processing_status: Optional[str] = None,
        alert_status: Optional[str] = None,
        alert_group_name: Optional[str] = None,
        req_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if processing_status:
            params["processing_status"] = processing_status
        if alert_status:
            params["alert_status"] = alert_status
        if alert_group_name:
            params["alert_group_name"] = alert_group_name
        if req_id:
            params["req_id"] = req_id
        payload = self._request("GET", "/api/v1/orders", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected orders response format")

    def get_order(self, order_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/orders/{order_id}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected order response format")

    def get_order_timeline(self, order_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/orders/{order_id}/timeline")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected order timeline response format")

    # Communications activity
    def list_communications(
        self,
        *,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if channel:
            params["channel"] = channel
        payload = self._request("GET", "/api/v1/communications/activity", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected communications activity response format")

    def get_communication(self, communication_id: str, *, limit: int = 1000) -> dict[str, Any]:
        for item in self.list_communications(limit=limit):
            if str(item.get("communication_id")) == str(communication_id):
                return item
        raise NotFoundError(f"Communication '{communication_id}' not found")

    # Suppressions
    def list_suppressions(
        self,
        *,
        status: Optional[str] = None,
        enabled: Optional[bool] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if enabled is not None:
            params["enabled"] = str(enabled).lower()
        if scope:
            params["scope"] = scope
        payload = self._request("GET", "/api/v1/suppressions", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected suppressions response format")

    def get_suppression(self, suppression_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/suppressions/{suppression_id}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected suppression response format")

    def create_suppression(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/v1/suppressions", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected create suppression response format")

    def cancel_suppression(self, suppression_id: int) -> dict[str, Any]:
        response = self._request("POST", f"/api/v1/suppressions/{suppression_id}/cancel")
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected cancel suppression response format")

    # Workflow activity / dishes
    def list_dishes(
        self,
        *,
        processing_status: Optional[str] = None,
        req_id: Optional[str] = None,
        order_id: Optional[int] = None,
        execution_ref: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if processing_status:
            params["processing_status"] = processing_status
        if req_id:
            params["req_id"] = req_id
        if order_id is not None:
            params["order_id"] = order_id
        if execution_ref:
            params["execution_ref"] = execution_ref
        payload = self._request("GET", "/api/v1/dishes", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected dishes response format")

    def get_dish(self, dish_id: int, *, limit: int = 1000) -> dict[str, Any]:
        for item in self.list_dishes(limit=limit):
            if int(item.get("id", -1)) == dish_id:
                return item
        raise NotFoundError(f"Workflow run '{dish_id}' not found")

    # Actions / ingredients
    def list_ingredients(
        self,
        *,
        execution_target: Optional[str] = None,
        task_key_template: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if execution_target:
            params["execution_target"] = execution_target
        if task_key_template:
            params["task_key_template"] = task_key_template
        payload = self._request("GET", "/api/v1/ingredients/", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected ingredients response format")

    def get_ingredient(self, ingredient_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/ingredients/{ingredient_id}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected ingredient response format")

    def create_ingredient(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/v1/ingredients/", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected create ingredient response format")

    def update_ingredient(self, ingredient_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PUT", f"/api/v1/ingredients/{ingredient_id}", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected update ingredient response format")

    def delete_ingredient(self, ingredient_id: int) -> dict[str, Any]:
        response = self._request("DELETE", f"/api/v1/ingredients/{ingredient_id}")
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected delete ingredient response format")

    # Workflows / recipes
    def list_recipes(
        self,
        *,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        if enabled is not None:
            params["enabled"] = str(enabled).lower()
        payload = self._request("GET", "/api/v1/recipes/", params=params)
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected recipes response format")

    def get_recipe(self, recipe_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/recipes/{recipe_id}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected recipe response format")

    def create_recipe(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/v1/recipes/", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected create recipe response format")

    def update_recipe(self, recipe_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PATCH", f"/api/v1/recipes/{recipe_id}", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected update recipe response format")

    def delete_recipe(self, recipe_id: int) -> dict[str, Any]:
        response = self._request("DELETE", f"/api/v1/recipes/{recipe_id}")
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected delete recipe response format")

    # Global communications policy
    def get_global_communications_policy(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/communications/policy")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected communications policy response format")

    def set_global_communications_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PUT", "/api/v1/communications/policy", json=payload)
        if isinstance(response, dict):
            return cast(dict[str, Any], response)
        raise PoundCakeClientError("Unexpected communications policy update response format")

    # Prometheus rules
    def list_rules(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/prometheus/rules")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        if isinstance(payload, list):
            return {"rules": cast(list[dict[str, Any]], payload), "source": "unknown"}
        raise PoundCakeClientError("Unexpected rule list response format")

    def get_rule(self, source_name: str, group_name: str, rule_name: str) -> dict[str, Any]:
        payload = self.list_rules()
        for rule in payload.get("rules", []):
            source = str(rule.get("crd") or rule.get("file") or "")
            if source != source_name:
                continue
            if str(rule.get("group") or "") != group_name:
                continue
            if str(rule.get("name") or "") != rule_name:
                continue
            return cast(dict[str, Any], rule)
        raise NotFoundError(
            f"Rule not found: source={source_name!r}, group={group_name!r}, rule={rule_name!r}"
        )

    def create_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
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
        raise PoundCakeClientError("Unexpected create rule response format")

    def update_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
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
        raise PoundCakeClientError("Unexpected update rule response format")

    def delete_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
    ) -> dict[str, Any]:
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
        raise PoundCakeClientError("Unexpected delete rule response format")

    # StackStorm action management
    def list_st2_actions(
        self,
        pack: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if pack:
            params["pack"] = pack
        payload = self._request("GET", "/api/v1/cook/actions", params=params)
        if isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            return cast(list[dict[str, Any]], payload["actions"])
        if isinstance(payload, list):
            return cast(list[dict[str, Any]], payload)
        raise PoundCakeClientError("Unexpected actions response format")

    def get_st2_action(self, action_ref: str) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/cook/actions/{action_ref}")
        if isinstance(payload, dict):
            return cast(dict[str, Any], payload)
        raise PoundCakeClientError("Unexpected action response format")

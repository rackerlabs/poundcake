"""HTTP client for the PoundCake CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar, cast

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from api.schemas.schemas import (
    AuthLoginRequest,
    AuthMeResponse,
    AuthPrincipalResponse,
    AuthProviderResponse,
    AuthRoleBindingCreate,
    AuthRoleBindingResponse,
    AuthRoleBindingUpdate,
    CommunicationActivityRecord,
    CommunicationPolicyResponse,
    CommunicationPolicyUpdate,
    DeleteResponse,
    DeviceAuthorizationPollRequest,
    DeviceAuthorizationPollResponse,
    DeviceAuthorizationStartRequest,
    DeviceAuthorizationStartResponse,
    DishDetailResponse,
    HealthResponse,
    IncidentTimelineResponse,
    IngredientCreate,
    IngredientResponse,
    IngredientUpdate,
    ObservabilityActivityRecord,
    ObservabilityOverviewResponse,
    OrderResponse,
    PrometheusRuleListResponse,
    PrometheusRuleMutationResponse,
    PrometheusRuleWriteRequest,
    RecipeCreate,
    RecipeDetailResponse,
    RecipeUpdate,
    SessionResponse,
    SettingsResponse,
    StatsResponse,
    SuppressionCreate,
    SuppressionDetailResponse,
    SuppressionResponse,
)
from api.core.http_client import request_with_retry_sync
from cli.session import SessionStore, StoredSession

ModelT = TypeVar("ModelT", bound=BaseModel)


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

    def _validate_model(self, payload: Any, model: type[ModelT], context: str) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise PoundCakeClientError(f"{context}: {exc}") from exc

    def _validate_model_dump(
        self, payload: Any, model: type[ModelT], context: str
    ) -> dict[str, Any]:
        validated = self._validate_model(payload, model, context)
        return cast(dict[str, Any], validated.model_dump(mode="json", by_alias=True))

    def _validate_list_dump(
        self, payload: Any, item_model: type[ModelT], context: str
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise PoundCakeClientError(context)
        validated: list[dict[str, Any]] = []
        for item in payload:
            model = self._validate_model(item, item_model, context)
            validated.append(cast(dict[str, Any], model.model_dump(mode="json", by_alias=True)))
        return validated

    def _validate_request_payload(
        self, payload: dict[str, Any], model: type[ModelT], context: str
    ) -> dict[str, Any]:
        validated = self._validate_model(payload, model, context)
        return cast(
            dict[str, Any],
            validated.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True),
        )

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
        validated = self._validate_model(
            payload, SessionResponse, "Unexpected login response format"
        )
        result = LoginResult(
            session_id=str(validated.session_id),
            username=str(validated.username),
            expires_at=str(validated.expires_at),
            provider=str(validated.provider),
            role=str(validated.role),
            display_name=(None if validated.display_name is None else str(validated.display_name)),
            is_superuser=bool(validated.is_superuser),
            permissions=[str(item) for item in validated.permissions] or None,
            token_type=str(validated.token_type or "Bearer"),
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
        request_payload = self._validate_request_payload(
            {"provider": provider, "username": username, "password": password},
            AuthLoginRequest,
            "Invalid login request payload",
        )
        payload = self._request(
            "POST",
            "/api/v1/auth/login",
            json=request_payload,
            use_session=False,
        )
        validated = self._validate_model(
            payload, SessionResponse, "Unexpected login response format"
        )
        return self._store_login_payload(validated.model_dump(mode="json", by_alias=True))

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
        return self._validate_model_dump(
            payload, SettingsResponse, "Unexpected settings response format"
        )

    def get_auth_providers(self) -> list[ProviderInfo]:
        payload = self._request("GET", "/api/v1/auth/providers", use_session=False)
        try:
            validated = TypeAdapter(list[AuthProviderResponse]).validate_python(payload)
        except ValidationError as exc:
            raise PoundCakeClientError(f"Unexpected auth providers response format: {exc}") from exc
        return [
            ProviderInfo(
                name=str(item.name),
                label=str(item.label),
                login_mode=str(item.login_mode),
                cli_login_mode=str(item.cli_login_mode),
                browser_login=bool(item.browser_login),
                device_login=bool(item.device_login),
                password_login=bool(item.password_login),
            )
            for item in validated
        ]

    def auth_me(self) -> AuthMeResult:
        payload = self._request("GET", "/api/v1/auth/me")
        validated = self._validate_model(
            payload, AuthMeResponse, "Unexpected auth me response format"
        )
        return AuthMeResult(
            username=str(validated.username),
            display_name=(None if validated.display_name is None else str(validated.display_name)),
            provider=str(validated.provider),
            role=str(validated.role),
            principal_type=str(validated.principal_type),
            principal_id=(int(validated.principal_id) if validated.principal_id else None),
            is_superuser=bool(validated.is_superuser),
            permissions=[str(item) for item in validated.permissions],
            groups=[str(item) for item in validated.groups],
            expires_at=(None if validated.expires_at is None else str(validated.expires_at)),
        )

    def start_device_login(self, provider: str) -> DeviceAuthorizationStart:
        request_payload = self._validate_request_payload(
            {"provider": provider},
            DeviceAuthorizationStartRequest,
            "Invalid device authorization request payload",
        )
        payload = self._request(
            "POST",
            "/api/v1/auth/device/start",
            json=request_payload,
            use_session=False,
        )
        validated = self._validate_model(
            payload,
            DeviceAuthorizationStartResponse,
            "Unexpected device authorization response format",
        )
        return DeviceAuthorizationStart(
            provider=str(validated.provider or provider),
            device_code=str(validated.device_code),
            user_code=str(validated.user_code),
            verification_uri=str(validated.verification_uri),
            verification_uri_complete=(
                None
                if validated.verification_uri_complete is None
                else str(validated.verification_uri_complete)
            ),
            expires_in=int(validated.expires_in),
            interval=int(validated.interval),
        )

    def poll_device_login(self, provider: str, device_code: str) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            {"provider": provider, "device_code": device_code},
            DeviceAuthorizationPollRequest,
            "Invalid device poll request payload",
        )
        payload = self._request(
            "POST",
            "/api/v1/auth/device/poll",
            json=request_payload,
            use_session=False,
        )
        validated = self._validate_model(
            payload,
            DeviceAuthorizationPollResponse,
            "Unexpected device poll response format",
        )
        if validated.session is not None:
            self._store_login_payload(validated.session.model_dump(mode="json", by_alias=True))
        return cast(dict[str, Any], validated.model_dump(mode="json", by_alias=True))

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
        return self._validate_list_dump(
            payload,
            AuthPrincipalResponse,
            "Unexpected auth principals response format",
        )

    def list_auth_bindings(self, *, provider: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] | None = None
        if provider:
            params = {"provider": provider}
        payload = self._request("GET", "/api/v1/auth/bindings", params=params)
        return self._validate_list_dump(
            payload,
            AuthRoleBindingResponse,
            "Unexpected auth bindings response format",
        )

    def create_auth_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            AuthRoleBindingCreate,
            "Invalid auth binding request payload",
        )
        result = self._request("POST", "/api/v1/auth/bindings", json=request_payload)
        return self._validate_model_dump(
            result,
            AuthRoleBindingResponse,
            "Unexpected auth binding response format",
        )

    def update_auth_binding(self, binding_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            AuthRoleBindingUpdate,
            "Invalid auth binding update payload",
        )
        result = self._request("PATCH", f"/api/v1/auth/bindings/{binding_id}", json=request_payload)
        return self._validate_model_dump(
            result,
            AuthRoleBindingResponse,
            "Unexpected auth binding response format",
        )

    def delete_auth_binding(self, binding_id: int) -> dict[str, Any]:
        result = self._request("DELETE", f"/api/v1/auth/bindings/{binding_id}")
        return self._validate_model_dump(
            result,
            DeleteResponse,
            "Unexpected auth binding delete response format",
        )

    # Health and overview
    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/health")
        return self._validate_model_dump(
            payload, HealthResponse, "Unexpected health response format"
        )

    def ready(self) -> dict[str, Any]:
        return self.health()

    def stats(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/stats")
        return self._validate_model_dump(payload, StatsResponse, "Unexpected stats response format")

    def observability_overview(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/observability/overview")
        return self._validate_model_dump(
            payload,
            ObservabilityOverviewResponse,
            "Unexpected observability overview response format",
        )

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
        return self._validate_list_dump(
            payload,
            ObservabilityActivityRecord,
            "Unexpected observability activity response format",
        )

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
        return self._validate_list_dump(payload, OrderResponse, "Unexpected orders response format")

    def get_order(self, order_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/orders/{order_id}")
        return self._validate_model_dump(payload, OrderResponse, "Unexpected order response format")

    def get_order_timeline(self, order_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/orders/{order_id}/timeline")
        return self._validate_model_dump(
            payload,
            IncidentTimelineResponse,
            "Unexpected order timeline response format",
        )

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
        return self._validate_list_dump(
            payload,
            CommunicationActivityRecord,
            "Unexpected communications activity response format",
        )

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
        return self._validate_list_dump(
            payload,
            SuppressionResponse,
            "Unexpected suppressions response format",
        )

    def get_suppression(self, suppression_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/suppressions/{suppression_id}")
        return self._validate_model_dump(
            payload,
            SuppressionDetailResponse,
            "Unexpected suppression response format",
        )

    def create_suppression(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            SuppressionCreate,
            "Invalid create suppression payload",
        )
        response = self._request("POST", "/api/v1/suppressions", json=request_payload)
        return self._validate_model_dump(
            response,
            SuppressionResponse,
            "Unexpected create suppression response format",
        )

    def cancel_suppression(self, suppression_id: int) -> dict[str, Any]:
        response = self._request("POST", f"/api/v1/suppressions/{suppression_id}/cancel")
        return self._validate_model_dump(
            response,
            SuppressionResponse,
            "Unexpected cancel suppression response format",
        )

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
        return self._validate_list_dump(
            payload, DishDetailResponse, "Unexpected dishes response format"
        )

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
        return self._validate_list_dump(
            payload,
            IngredientResponse,
            "Unexpected ingredients response format",
        )

    def get_ingredient(self, ingredient_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/ingredients/{ingredient_id}")
        return self._validate_model_dump(
            payload,
            IngredientResponse,
            "Unexpected ingredient response format",
        )

    def create_ingredient(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            IngredientCreate,
            "Invalid create ingredient payload",
        )
        response = self._request("POST", "/api/v1/ingredients/", json=request_payload)
        return self._validate_model_dump(
            response,
            IngredientResponse,
            "Unexpected create ingredient response format",
        )

    def update_ingredient(self, ingredient_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            IngredientUpdate,
            "Invalid update ingredient payload",
        )
        response = self._request(
            "PUT", f"/api/v1/ingredients/{ingredient_id}", json=request_payload
        )
        return self._validate_model_dump(
            response,
            IngredientResponse,
            "Unexpected update ingredient response format",
        )

    def delete_ingredient(self, ingredient_id: int) -> dict[str, Any]:
        response = self._request("DELETE", f"/api/v1/ingredients/{ingredient_id}")
        return self._validate_model_dump(
            response,
            DeleteResponse,
            "Unexpected delete ingredient response format",
        )

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
        return self._validate_list_dump(
            payload, RecipeDetailResponse, "Unexpected recipes response format"
        )

    def get_recipe(self, recipe_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/recipes/{recipe_id}")
        return self._validate_model_dump(
            payload, RecipeDetailResponse, "Unexpected recipe response format"
        )

    def create_recipe(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            RecipeCreate,
            "Invalid create recipe payload",
        )
        response = self._request("POST", "/api/v1/recipes/", json=request_payload)
        return self._validate_model_dump(
            response,
            RecipeDetailResponse,
            "Unexpected create recipe response format",
        )

    def update_recipe(self, recipe_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            RecipeUpdate,
            "Invalid update recipe payload",
        )
        response = self._request("PATCH", f"/api/v1/recipes/{recipe_id}", json=request_payload)
        return self._validate_model_dump(
            response,
            RecipeDetailResponse,
            "Unexpected update recipe response format",
        )

    def delete_recipe(self, recipe_id: int) -> dict[str, Any]:
        response = self._request("DELETE", f"/api/v1/recipes/{recipe_id}")
        return self._validate_model_dump(
            response,
            DeleteResponse,
            "Unexpected delete recipe response format",
        )

    # Global communications policy
    def get_global_communications_policy(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/communications/policy")
        return self._validate_model_dump(
            payload,
            CommunicationPolicyResponse,
            "Unexpected communications policy response format",
        )

    def set_global_communications_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            payload,
            CommunicationPolicyUpdate,
            "Invalid communications policy payload",
        )
        response = self._request("PUT", "/api/v1/communications/policy", json=request_payload)
        return self._validate_model_dump(
            response,
            CommunicationPolicyResponse,
            "Unexpected communications policy update response format",
        )

    # Prometheus rules
    def list_rules(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/v1/prometheus/rules")
        return self._validate_model_dump(
            payload,
            PrometheusRuleListResponse,
            "Unexpected rule list response format",
        )

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
        request_payload = self._validate_request_payload(
            rule_data,
            PrometheusRuleWriteRequest,
            "Invalid create rule payload",
        )
        payload = self._request(
            "POST",
            "/api/v1/prometheus/rules",
            json=request_payload,
            params={
                "rule_name": rule_name,
                "group_name": group_name,
                "file_name": source_name,
            },
        )
        return self._validate_model_dump(
            payload,
            PrometheusRuleMutationResponse,
            "Unexpected create rule response format",
        )

    def update_rule(
        self,
        source_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        request_payload = self._validate_request_payload(
            rule_data,
            PrometheusRuleWriteRequest,
            "Invalid update rule payload",
        )
        payload = self._request(
            "PUT",
            f"/api/v1/prometheus/rules/{rule_name}",
            json=request_payload,
            params={
                "group_name": group_name,
                "file_name": source_name,
            },
        )
        return self._validate_model_dump(
            payload,
            PrometheusRuleMutationResponse,
            "Unexpected update rule response format",
        )

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
        return self._validate_model_dump(
            payload,
            PrometheusRuleMutationResponse,
            "Unexpected delete rule response format",
        )

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

#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Authentication and authorization services for PoundCake."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import re
import secrets
import ssl
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.config import get_settings
from api.core.http_client import request_with_retry
from api.core.logging import get_logger
from api.models.models import AuthPrincipal, AuthRoleBinding
from api.types import AuthBindingType, AuthPrincipalType, AuthProvider, AuthRole

logger = get_logger(__name__)

ROLE_PRECEDENCE: dict[AuthRole, int] = {
    "reader": 0,
    "operator": 1,
    "admin": 2,
    "service": 3,
}

ROLE_PERMISSIONS: dict[AuthRole, list[str]] = {
    "reader": ["read"],
    "operator": [
        "read",
        "manage_alert_rules",
        "manage_ingredients",
        "manage_recipes",
        "manage_suppressions",
    ],
    "admin": [
        "read",
        "manage_access",
        "manage_alert_rules",
        "manage_auth",
        "manage_global_communications",
        "manage_ingredients",
        "manage_recipes",
        "manage_suppressions",
    ],
    "service": ["read", "service"],
}

HUMAN_ROLES: set[AuthRole] = {"reader", "operator", "admin"}

_MEMORY_STATE: dict[str, tuple[dict[str, Any], datetime]] = {}
_SESSION_STORE: SessionStore | None = None
_SESSION_STORE_KEY: tuple[Any, ...] | None = None


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def normalize_groups(groups: list[str] | None) -> list[str]:
    """Return a stable, de-duplicated group list."""
    if not groups:
        return []
    seen: dict[str, str] = {}
    for group in groups:
        value = str(group or "").strip()
        if not value:
            continue
        seen[value.casefold()] = value
    return sorted(seen.values(), key=str.casefold)


def highest_role(roles: list[str]) -> AuthRole | None:
    """Pick the highest-precedence role from a list."""
    best: AuthRole | None = None
    for role in roles:
        normalized = str(role or "").strip().lower()
        if normalized not in ROLE_PRECEDENCE:
            continue
        candidate = normalized  # type: ignore[assignment]
        if best is None or ROLE_PRECEDENCE[candidate] > ROLE_PRECEDENCE[best]:
            best = candidate
    return best


def permissions_for_role(role: AuthRole, *, is_superuser: bool = False) -> list[str]:
    """Expand a role into concrete permissions."""
    permissions = list(ROLE_PERMISSIONS[role])
    if is_superuser and "superuser" not in permissions:
        permissions.append("superuser")
    return permissions


@dataclass
class AuthIdentity:
    """Authenticated identity before RBAC resolution."""

    provider: AuthProvider
    subject_id: str
    username: str
    display_name: str | None = None
    groups: list[str] = field(default_factory=list)
    principal_type: AuthPrincipalType = "user"
    is_superuser: bool = False

    def normalized_groups(self) -> list[str]:
        return normalize_groups(self.groups)


@dataclass
class AuthContext:
    """Resolved principal metadata stored in sessions and request state."""

    provider: AuthProvider
    subject_id: str
    username: str
    display_name: str | None
    groups: list[str]
    role: AuthRole
    principal_type: AuthPrincipalType
    is_superuser: bool = False
    permissions: list[str] = field(default_factory=list)
    principal_id: int | None = None
    session_id: str | None = None
    expires_at: str | None = None

    def is_human(self) -> bool:
        return self.principal_type == "user"

    def to_session_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceAuthorizationStart:
    """Auth0 device authorization payload."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


class AuthError(RuntimeError):
    """Base auth service error."""


class InvalidCredentialsError(AuthError):
    """Raised when provider credentials are rejected."""


class ProviderConfigurationError(AuthError):
    """Raised when a configured auth provider is incomplete."""


class AccessDeniedError(AuthError):
    """Raised when login succeeded but no role binding matches."""


class DeviceAuthorizationPending(AuthError):
    """Raised when an Auth0 device flow has not completed yet."""


class DeviceAuthorizationExpired(AuthError):
    """Raised when an Auth0 device flow expired."""


class SessionStore:
    """Persist auth sessions and short-lived auth state."""

    def __init__(self) -> None:
        settings = get_settings()
        self.prefix = settings.auth_redis_prefix
        self.use_memory = settings.testing or not settings.redis_enabled
        self._redis: Redis | None = None
        if not self.use_memory:
            self._redis = Redis.from_url(
                settings.redis_url,
                password=settings.redis_password or None,
                decode_responses=True,
            )

    def _redis_key(self, kind: str, key: str) -> str:
        return f"{self.prefix}:{kind}:{key}"

    async def create_session(self, context: AuthContext, *, ttl_seconds: int) -> AuthContext:
        context.session_id = secrets.token_urlsafe(32)
        context.expires_at = (utc_now() + timedelta(seconds=ttl_seconds)).isoformat()
        await self.set_value(
            "session", context.session_id, context.to_session_payload(), ttl_seconds
        )
        return context

    async def get_session(self, session_id: str | None) -> AuthContext | None:
        if not session_id:
            return None
        payload = await self.get_value("session", session_id)
        if not isinstance(payload, dict):
            return None
        try:
            return AuthContext(
                provider=str(payload["provider"]),  # type: ignore[arg-type]
                subject_id=str(payload["subject_id"]),
                username=str(payload["username"]),
                display_name=(
                    None
                    if payload.get("display_name") is None
                    else str(payload.get("display_name"))
                ),
                groups=normalize_groups(payload.get("groups")),
                role=str(payload["role"]),  # type: ignore[arg-type]
                principal_type=str(payload["principal_type"]),  # type: ignore[arg-type]
                is_superuser=bool(payload.get("is_superuser")),
                permissions=[str(item) for item in payload.get("permissions") or []],
                principal_id=(
                    int(payload["principal_id"])
                    if payload.get("principal_id") is not None
                    else None
                ),
                session_id=str(payload.get("session_id") or session_id),
                expires_at=(
                    None if payload.get("expires_at") is None else str(payload.get("expires_at"))
                ),
            )
        except KeyError:
            return None

    async def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        await self.delete_value("session", session_id)

    async def put_state(
        self, kind: str, key: str, payload: dict[str, Any], *, ttl_seconds: int
    ) -> None:
        await self.set_value(kind, key, payload, ttl_seconds)

    async def pop_state(self, kind: str, key: str) -> dict[str, Any] | None:
        payload = await self.get_value(kind, key)
        await self.delete_value(kind, key)
        if isinstance(payload, dict):
            return payload
        return None

    async def set_value(
        self, kind: str, key: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        if self.use_memory:
            _MEMORY_STATE[self._redis_key(kind, key)] = (
                payload,
                utc_now() + timedelta(seconds=ttl_seconds),
            )
            return
        assert self._redis is not None
        await self._redis.setex(self._redis_key(kind, key), ttl_seconds, json.dumps(payload))

    async def get_value(self, kind: str, key: str) -> dict[str, Any] | None:
        storage_key = self._redis_key(kind, key)
        if self.use_memory:
            entry = _MEMORY_STATE.get(storage_key)
            if not entry:
                return None
            payload, expires_at = entry
            if expires_at <= utc_now():
                _MEMORY_STATE.pop(storage_key, None)
                return None
            return dict(payload)
        assert self._redis is not None
        raw = await self._redis.get(storage_key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    async def delete_value(self, kind: str, key: str) -> None:
        storage_key = self._redis_key(kind, key)
        if self.use_memory:
            _MEMORY_STATE.pop(storage_key, None)
            return
        assert self._redis is not None
        await self._redis.delete(storage_key)


def get_session_store() -> SessionStore:
    """Return the active auth session store."""
    global _SESSION_STORE, _SESSION_STORE_KEY
    settings = get_settings()
    key = (
        settings.testing,
        settings.redis_enabled,
        settings.redis_url,
        settings.redis_password,
        settings.auth_redis_prefix,
    )
    if _SESSION_STORE is None or _SESSION_STORE_KEY != key:
        _SESSION_STORE = SessionStore()
        _SESSION_STORE_KEY = key
    return _SESSION_STORE


def get_local_superuser_credentials() -> tuple[str, str] | None:
    """Load the bootstrap superuser credentials."""
    settings = get_settings()

    if not settings.auth_enabled or not settings.auth_local_enabled:
        return None

    if settings.auth_username and settings.auth_password:
        return (settings.auth_username, settings.auth_password)

    try:
        k8s_client_module = importlib.import_module("kubernetes.client")
        k8s_config_module = importlib.import_module("kubernetes.config")

        try:
            k8s_config_module.load_incluster_config()
        except Exception:
            k8s_config_module.load_kube_config()

        v1 = k8s_client_module.CoreV1Api()
        secret = v1.read_namespaced_secret(
            name=settings.auth_secret_name,
            namespace=settings.auth_secret_namespace,
        )
        username = base64.b64decode(secret.data["username"]).decode("utf-8")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")
        return (username, password)
    except Exception as exc:
        logger.debug("Local superuser secret unavailable", extra={"error": str(exc)})

    if settings.auth_dev_username and settings.auth_dev_password:
        return (settings.auth_dev_username, settings.auth_dev_password)

    return None


def get_enabled_provider_metadata() -> list[dict[str, Any]]:
    """Describe enabled auth providers for UI and CLI discovery."""
    settings = get_settings()
    providers: list[dict[str, Any]] = []

    if get_local_superuser_credentials():
        providers.append(
            {
                "name": "local",
                "label": "Local Superuser",
                "login_mode": "password",
                "cli_login_mode": "password",
                "browser_login": False,
                "device_login": False,
                "password_login": True,
            }
        )

    if settings.auth_ad_enabled and settings.auth_ad_server_uri:
        providers.append(
            {
                "name": "active_directory",
                "label": "Active Directory",
                "login_mode": "password",
                "cli_login_mode": "password",
                "browser_login": False,
                "device_login": False,
                "password_login": True,
            }
        )

    auth0_browser = auth0_browser_login_enabled(settings)
    auth0_device = auth0_device_login_enabled(settings)
    if auth0_browser or auth0_device:
        providers.append(
            {
                "name": "auth0",
                "label": "Auth0",
                "login_mode": "oidc" if auth0_browser else "device",
                "cli_login_mode": "device" if auth0_device else "unavailable",
                "browser_login": auth0_browser,
                "device_login": auth0_device,
                "password_login": False,
            }
        )

    return providers


def provider_names() -> list[str]:
    """Return enabled provider names."""
    return [str(item["name"]) for item in get_enabled_provider_metadata()]


def auth0_browser_login_enabled(settings: Any | None = None) -> bool:
    """Return whether Auth0 browser login is configured."""
    settings = settings or get_settings()
    return bool(
        settings.auth_auth0_enabled
        and settings.auth_auth0_domain
        and settings.auth_auth0_ui_enabled
        and settings.auth_auth0_ui_client_id
    )


def auth0_device_login_enabled(settings: Any | None = None) -> bool:
    """Return whether Auth0 CLI device login is configured."""
    settings = settings or get_settings()
    return bool(
        settings.auth_auth0_enabled
        and settings.auth_auth0_domain
        and settings.auth_auth0_cli_enabled
        and settings.auth_auth0_cli_client_id
    )


async def authenticate_password_provider(
    provider: str,
    username: str,
    password: str,
) -> AuthIdentity:
    """Authenticate a username/password against the selected provider."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "local":
        return await authenticate_local_superuser(username, password)
    if normalized_provider == "active_directory":
        return await authenticate_active_directory(username, password)
    raise ProviderConfigurationError(f"Provider '{provider}' does not support password login")


async def authenticate_local_superuser(username: str, password: str) -> AuthIdentity:
    """Validate the bootstrap superuser credentials."""
    credentials = get_local_superuser_credentials()
    if not credentials:
        raise ProviderConfigurationError("Local superuser credentials are not configured")
    configured_username, configured_password = credentials
    if not (
        secrets.compare_digest(username, configured_username)
        and secrets.compare_digest(password, configured_password)
    ):
        raise InvalidCredentialsError("Invalid username or password")
    return AuthIdentity(
        provider="local",
        subject_id=configured_username,
        username=configured_username,
        display_name=configured_username,
        groups=[],
        principal_type="user",
        is_superuser=True,
    )


def _sync_authenticate_active_directory(username: str, password: str) -> AuthIdentity:
    from ldap3 import ALL, Connection, Server, Tls  # type: ignore[import-untyped]
    from ldap3.utils.conv import escape_filter_chars  # type: ignore[import-untyped]

    settings = get_settings()
    if not settings.auth_ad_enabled or not settings.auth_ad_server_uri:
        raise ProviderConfigurationError("Active Directory is not enabled")

    tls = None
    if settings.auth_ad_use_ssl:
        tls_validate = ssl.CERT_REQUIRED if settings.auth_ad_validate_tls else ssl.CERT_NONE
        tls = Tls(
            validate=tls_validate,
            ca_certs_file=settings.auth_ad_ca_certs_file or None,
        )

    server = Server(
        settings.auth_ad_server_uri,
        use_ssl=settings.auth_ad_use_ssl,
        get_info=ALL,
        tls=tls,
    )

    service_user = settings.auth_ad_bind_dn or username
    service_password = settings.auth_ad_bind_password or password
    service_conn = Connection(server, user=service_user, password=service_password, auto_bind=True)

    safe_username = escape_filter_chars(username)
    search_filter = settings.auth_ad_user_filter.format(username=safe_username)
    attributes = [
        settings.auth_ad_username_attribute,
        settings.auth_ad_display_name_attribute,
        settings.auth_ad_subject_attribute,
        settings.auth_ad_group_attribute,
    ]
    found = service_conn.search(
        search_base=settings.auth_ad_user_base_dn,
        search_filter=search_filter,
        attributes=attributes,
    )
    if not found or not service_conn.entries:
        raise InvalidCredentialsError("Invalid username or password")

    entry = service_conn.entries[0]
    user_dn = str(entry.entry_dn)

    user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
    user_conn.unbind()

    username_value = getattr(entry, settings.auth_ad_username_attribute, None)
    display_value = getattr(entry, settings.auth_ad_display_name_attribute, None)
    subject_value = getattr(entry, settings.auth_ad_subject_attribute, None)
    raw_groups = getattr(entry, settings.auth_ad_group_attribute, None)

    username_text = str(getattr(username_value, "value", "") or "").strip() or username
    display_text = str(getattr(display_value, "value", "") or "").strip() or username_text
    subject_text = str(getattr(subject_value, "value", "") or "").strip() or user_dn

    group_values = getattr(raw_groups, "values", None)
    if group_values is None:
        value = getattr(raw_groups, "value", None)
        if isinstance(value, list):
            group_values = value
        elif value:
            group_values = [value]
        else:
            group_values = []

    group_name_pattern = re.compile(settings.auth_ad_group_name_regex)
    groups: list[str] = []
    for raw_group in group_values:
        value = str(raw_group or "").strip()
        if not value:
            continue
        match = group_name_pattern.search(value)
        groups.append(match.group(1) if match else value)

    return AuthIdentity(
        provider="active_directory",
        subject_id=subject_text,
        username=username_text,
        display_name=display_text,
        groups=normalize_groups(groups),
        principal_type="user",
        is_superuser=False,
    )


async def authenticate_active_directory(username: str, password: str) -> AuthIdentity:
    """Validate Active Directory credentials and group membership."""
    try:
        return await asyncio.to_thread(_sync_authenticate_active_directory, username, password)
    except InvalidCredentialsError:
        raise
    except ProviderConfigurationError:
        raise
    except Exception as exc:
        raise InvalidCredentialsError(str(exc)) from exc


def _auth0_base_url() -> str:
    settings = get_settings()
    if not (settings.auth_auth0_enabled and settings.auth_auth0_domain):
        raise ProviderConfigurationError("Auth0 is not enabled")
    domain = settings.auth_auth0_domain.strip().rstrip("/")
    if domain.startswith("https://"):
        return domain
    return f"https://{domain}"


def _auth0_common_form_fields(*, client_id: str, client_secret: str = "") -> dict[str, str]:
    settings = get_settings()
    payload = {"client_id": client_id}
    if client_secret:
        payload["client_secret"] = client_secret
    if settings.auth_auth0_audience:
        payload["audience"] = settings.auth_auth0_audience
    if settings.auth_auth0_scope:
        payload["scope"] = settings.auth_auth0_scope
    return payload


async def get_auth0_authorize_url(state: str, redirect_uri: str) -> str:
    """Construct the Auth0 browser login URL."""
    settings = get_settings()
    if not auth0_browser_login_enabled(settings):
        raise ProviderConfigurationError("Auth0 browser login is not enabled")
    params = {
        "response_type": "code",
        "client_id": settings.auth_auth0_ui_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.auth_auth0_scope,
        "state": state,
    }
    if settings.auth_auth0_audience:
        params["audience"] = settings.auth_auth0_audience
    if settings.auth_auth0_organization:
        params["organization"] = settings.auth_auth0_organization
    if settings.auth_auth0_connection:
        params["connection"] = settings.auth_auth0_connection
    return f"{_auth0_base_url()}/authorize?{urlencode(params)}"


async def start_auth0_device_authorization() -> DeviceAuthorizationStart:
    """Begin an Auth0 device flow."""
    settings = get_settings()
    if not auth0_device_login_enabled(settings):
        raise ProviderConfigurationError("Auth0 CLI device login is not enabled")
    payload = _auth0_common_form_fields(
        client_id=settings.auth_auth0_cli_client_id,
        client_secret=settings.auth_auth0_cli_client_secret,
    )
    response = await request_with_retry(
        "POST",
        f"{_auth0_base_url()}/oauth/device/code",
        data=payload,
    )
    if response.status_code >= 400:
        raise ProviderConfigurationError("Auth0 device authorization could not be started")
    data = response.json()
    return DeviceAuthorizationStart(
        device_code=str(data["device_code"]),
        user_code=str(data["user_code"]),
        verification_uri=str(data["verification_uri"]),
        verification_uri_complete=(
            None
            if data.get("verification_uri_complete") is None
            else str(data.get("verification_uri_complete"))
        ),
        expires_in=int(data.get("expires_in") or 0),
        interval=int(data.get("interval") or 5),
    )


async def _auth0_fetch_userinfo(access_token: str) -> dict[str, Any]:
    response = await request_with_retry(
        "GET",
        f"{_auth0_base_url()}/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code >= 400:
        raise InvalidCredentialsError("Auth0 user profile lookup failed")
    data = response.json()
    return data if isinstance(data, dict) else {}


def _auth0_identity_from_profile(profile: dict[str, Any]) -> AuthIdentity:
    settings = get_settings()
    groups_value = profile.get(settings.auth_auth0_groups_claim) or []
    if isinstance(groups_value, str):
        groups = [groups_value]
    elif isinstance(groups_value, list):
        groups = [str(item) for item in groups_value]
    else:
        groups = []

    username = str(
        profile.get(settings.auth_auth0_username_claim)
        or profile.get("email")
        or profile.get("nickname")
        or profile.get("name")
        or profile.get("sub")
        or ""
    ).strip()
    subject_id = str(
        profile.get(settings.auth_auth0_subject_claim) or profile.get("sub") or ""
    ).strip()
    if not username or not subject_id:
        raise InvalidCredentialsError("Auth0 profile did not include a usable identity")

    display_name = str(
        profile.get(settings.auth_auth0_display_name_claim) or profile.get("name") or username
    ).strip()

    return AuthIdentity(
        provider="auth0",
        subject_id=subject_id,
        username=username,
        display_name=display_name or username,
        groups=normalize_groups(groups),
        principal_type="user",
        is_superuser=False,
    )


async def authenticate_auth0_authorization_code(code: str, redirect_uri: str) -> AuthIdentity:
    """Exchange an Auth0 browser auth code for an identity."""
    settings = get_settings()
    if not auth0_browser_login_enabled(settings):
        raise ProviderConfigurationError("Auth0 browser login is not enabled")
    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.auth_auth0_ui_client_id,
        "client_secret": settings.auth_auth0_ui_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    response = await request_with_retry(
        "POST",
        f"{_auth0_base_url()}/oauth/token",
        json=payload,
    )
    if response.status_code >= 400:
        raise InvalidCredentialsError("Auth0 code exchange failed")
    data = response.json()
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise InvalidCredentialsError("Auth0 response did not include an access token")
    profile = await _auth0_fetch_userinfo(access_token)
    return _auth0_identity_from_profile(profile)


async def authenticate_auth0_device_code(device_code: str) -> AuthIdentity:
    """Poll an Auth0 device code until the user authorizes it."""
    settings = get_settings()
    if not auth0_device_login_enabled(settings):
        raise ProviderConfigurationError("Auth0 CLI device login is not enabled")
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": settings.auth_auth0_cli_client_id,
    }
    if settings.auth_auth0_cli_client_secret:
        payload["client_secret"] = settings.auth_auth0_cli_client_secret
    response = await request_with_retry(
        "POST",
        f"{_auth0_base_url()}/oauth/token",
        data=payload,
        retry_statuses=[],
    )
    if response.status_code >= 400:
        data = response.json()
        error = str(data.get("error") or "").strip().lower() if isinstance(data, dict) else ""
        if error in {"authorization_pending", "slow_down"}:
            raise DeviceAuthorizationPending("Waiting for Auth0 approval")
        if error in {"expired_token", "access_denied"}:
            raise DeviceAuthorizationExpired("The Auth0 device login expired or was denied")
        raise InvalidCredentialsError("Auth0 device authorization failed")
    data = response.json()
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise InvalidCredentialsError("Auth0 response did not include an access token")
    profile = await _auth0_fetch_userinfo(access_token)
    return _auth0_identity_from_profile(profile)


async def upsert_principal(db: AsyncSession, identity: AuthIdentity) -> AuthPrincipal:
    """Create or refresh the stored principal record for an external user."""
    statement = select(AuthPrincipal).where(
        AuthPrincipal.provider == identity.provider,
        AuthPrincipal.subject_id == identity.subject_id,
    )
    principal = (await db.execute(statement)).scalar_one_or_none()
    if principal is None:
        principal = AuthPrincipal(
            provider=identity.provider,
            subject_id=identity.subject_id,
            username=identity.username,
            display_name=identity.display_name,
            principal_type=identity.principal_type,
            groups_json=identity.normalized_groups(),
            last_seen_at=utc_now(),
        )
        db.add(principal)
        await db.flush()
        return principal

    principal.username = identity.username
    principal.display_name = identity.display_name
    principal.principal_type = identity.principal_type
    principal.groups_json = identity.normalized_groups()
    principal.last_seen_at = utc_now()
    await db.flush()
    return principal


async def get_principal_by_id(db: AsyncSession, principal_id: int) -> AuthPrincipal | None:
    """Look up a principal by database id."""
    return await db.get(AuthPrincipal, principal_id)


async def list_principals(
    db: AsyncSession,
    *,
    provider: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuthPrincipal]:
    """List observed principals for access management."""
    statement = select(AuthPrincipal).order_by(AuthPrincipal.username.asc())
    if provider:
        statement = statement.where(AuthPrincipal.provider == provider)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                AuthPrincipal.username.ilike(pattern),
                AuthPrincipal.display_name.ilike(pattern),
            )
        )
    statement = statement.offset(offset).limit(limit)
    return list((await db.execute(statement)).scalars().all())


async def list_role_bindings(
    db: AsyncSession,
    *,
    provider: str | None = None,
) -> list[AuthRoleBinding]:
    """Return configured RBAC bindings."""
    statement = select(AuthRoleBinding).order_by(
        AuthRoleBinding.provider.asc(),
        AuthRoleBinding.binding_type.asc(),
        AuthRoleBinding.id.asc(),
    )
    statement = statement.options(selectinload(AuthRoleBinding.principal))
    if provider:
        statement = statement.where(AuthRoleBinding.provider == provider)
    return list((await db.execute(statement)).scalars().unique().all())


async def get_role_binding(db: AsyncSession, binding_id: int) -> AuthRoleBinding | None:
    """Load a single RBAC binding."""
    return await db.get(AuthRoleBinding, binding_id)


async def create_role_binding(
    db: AsyncSession,
    *,
    provider: str,
    binding_type: AuthBindingType,
    role: AuthRole,
    principal_id: int | None,
    external_group: str | None,
    created_by: str | None,
) -> AuthRoleBinding:
    """Create a provider-scoped RBAC binding."""
    binding = AuthRoleBinding(
        provider=provider,
        binding_type=binding_type,
        role=role,
        principal_id=principal_id,
        external_group=(None if external_group is None else external_group.strip() or None),
        created_by=(None if created_by is None else created_by.strip() or None),
    )
    db.add(binding)
    await db.flush()
    return binding


async def update_role_binding(
    db: AsyncSession,
    binding: AuthRoleBinding,
    *,
    role: AuthRole | None = None,
    external_group: str | None = None,
) -> AuthRoleBinding:
    """Update an existing RBAC binding."""
    if role is not None:
        binding.role = role
    if binding.binding_type == "group" and external_group is not None:
        binding.external_group = external_group.strip() or None
    await db.flush()
    return binding


async def delete_role_binding(db: AsyncSession, binding: AuthRoleBinding) -> None:
    """Delete an RBAC binding."""
    await db.delete(binding)


async def resolve_role_for_identity(
    db: AsyncSession,
    identity: AuthIdentity,
    principal: AuthPrincipal | None = None,
) -> tuple[AuthRole | None, AuthPrincipal | None]:
    """Resolve the effective role for a user identity."""
    if identity.provider == "local" and identity.is_superuser:
        return ("admin", None)

    principal = principal or await upsert_principal(db, identity)

    explicit_binding = (
        await db.execute(
            select(AuthRoleBinding).where(
                AuthRoleBinding.provider == identity.provider,
                AuthRoleBinding.binding_type == "user",
                AuthRoleBinding.principal_id == principal.id,
            )
        )
    ).scalar_one_or_none()
    if explicit_binding is not None:
        return (str(explicit_binding.role), principal)  # type: ignore[return-value]

    groups = identity.normalized_groups()
    if not groups:
        return (None, principal)

    group_bindings = (
        (
            await db.execute(
                select(AuthRoleBinding).where(
                    AuthRoleBinding.provider == identity.provider,
                    AuthRoleBinding.binding_type == "group",
                    AuthRoleBinding.external_group.in_(groups),
                )
            )
        )
        .scalars()
        .all()
    )
    matched_role = highest_role([binding.role for binding in group_bindings])
    return (matched_role, principal)


def build_auth_context(
    identity: AuthIdentity,
    role: AuthRole,
    *,
    principal: AuthPrincipal | None = None,
) -> AuthContext:
    """Build the resolved auth context returned to routes and clients."""
    return AuthContext(
        provider=identity.provider,
        subject_id=identity.subject_id,
        username=identity.username,
        display_name=identity.display_name or identity.username,
        groups=identity.normalized_groups(),
        role=role,
        principal_type=identity.principal_type,
        is_superuser=identity.is_superuser,
        permissions=permissions_for_role(role, is_superuser=identity.is_superuser),
        principal_id=None if principal is None else principal.id,
    )


async def build_login_context(db: AsyncSession, identity: AuthIdentity) -> AuthContext:
    """Resolve a newly authenticated identity into a session-ready context."""
    role, principal = await resolve_role_for_identity(db, identity)
    if role is None:
        raise AccessDeniedError("No PoundCake role binding matches this user")
    return build_auth_context(identity, role, principal=principal)


def service_token_context() -> AuthContext:
    """Return the static service principal context."""
    return AuthContext(
        provider="service",
        subject_id="service-token",
        username="service",
        display_name="Internal Service",
        groups=[],
        role="service",
        principal_type="service",
        is_superuser=False,
        permissions=permissions_for_role("service"),
        principal_id=None,
    )


async def rehydrate_session_context(
    db: AsyncSession,
    session_id: str | None,
) -> tuple[AuthContext | None, str | None]:
    """Load session state and refresh RBAC from current bindings."""
    store = get_session_store()
    stored = await store.get_session(session_id)
    if stored is None:
        return (None, None)

    if stored.role == "service" or stored.principal_type == "service":
        return (stored, None)

    if stored.is_superuser and stored.provider == "local":
        stored.role = "admin"
        stored.permissions = permissions_for_role("admin", is_superuser=True)
        return (stored, None)

    identity = AuthIdentity(
        provider=stored.provider,
        subject_id=stored.subject_id,
        username=stored.username,
        display_name=stored.display_name,
        groups=stored.groups,
        principal_type=stored.principal_type,
        is_superuser=stored.is_superuser,
    )
    principal = None
    if stored.principal_id is not None:
        principal = await get_principal_by_id(db, stored.principal_id)
    role, principal = await resolve_role_for_identity(db, identity, principal=principal)
    if role is None:
        return (None, "No PoundCake role binding matches this session")

    refreshed = build_auth_context(identity, role, principal=principal)
    refreshed.session_id = stored.session_id
    refreshed.expires_at = stored.expires_at
    return (refreshed, None)


def _is_public_path(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    public_paths = {
        "/",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/live",
        "/api/v1/ready",
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/providers",
        "/api/v1/auth/oidc/login",
        "/api/v1/auth/oidc/callback",
        "/api/v1/auth/device/start",
        "/api/v1/auth/device/poll",
        "/api/v1/cook/packs",
    }
    return path in public_paths or path.startswith("/static/")


def is_request_public(path: str, method: str) -> bool:
    """Determine whether an incoming request bypasses auth."""
    return _is_public_path(path, method.upper())


def _service_only_path(path: str, method: str) -> bool:
    if path == "/api/v1/webhook":
        return True
    if path == "/api/v1/suppressions/run-lifecycle":
        return True
    if path.startswith("/api/v1/orders") and method != "GET":
        return True
    if path.startswith("/api/v1/dishes") and method != "GET":
        return True
    if path.startswith("/api/v1/cook/") and method != "GET":
        return True
    return False


def request_role_requirement(path: str, method: str) -> AuthRole | None:
    """Map API routes to the minimum role required."""
    normalized_method = method.upper()

    if is_request_public(path, normalized_method):
        return None

    if _service_only_path(path, normalized_method):
        return "service"

    if path.startswith("/api/v1/auth/bindings") or path.startswith("/api/v1/auth/principals"):
        return "admin"

    if path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
        return "reader"

    if path == "/api/v1/communications/policy" and normalized_method == "PUT":
        return "admin"

    if path.startswith("/api/v1/ingredients") and normalized_method != "GET":
        return "operator"

    if path.startswith("/api/v1/recipes") and normalized_method != "GET":
        return "operator"

    if path.startswith("/api/v1/prometheus") and normalized_method != "GET":
        return "operator"

    if path.startswith("/api/v1/suppressions") and normalized_method != "GET":
        return "operator"

    if normalized_method == "GET":
        return "reader"

    return "admin"


def is_authorized_for_role(context: AuthContext, required_role: AuthRole) -> bool:
    """Check whether a resolved context satisfies a request requirement."""
    if required_role == "service":
        return context.role == "service"

    if context.role == "service":
        return required_role == "reader"

    if context.is_superuser:
        return True

    if required_role == "reader":
        return context.role in HUMAN_ROLES
    if required_role == "operator":
        return context.role in {"operator", "admin"}
    if required_role == "admin":
        return context.role == "admin"
    return False


def ensure_request_authorized(context: AuthContext, path: str, method: str) -> None:
    """Raise when the principal cannot perform the request."""
    required_role = request_role_requirement(path, method)
    if required_role is None:
        return
    if not is_authorized_for_role(context, required_role):
        raise AccessDeniedError(f"{context.role} role cannot access {method.upper()} {path}")


def build_auth_callback_url(base_url: str) -> str:
    """Return the Auth0 callback URL for this deployment."""
    settings = get_settings()
    if settings.auth_auth0_ui_callback_url:
        return settings.auth_auth0_ui_callback_url
    return f"{base_url.rstrip('/')}/api/v1/auth/oidc/callback"

#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Authentication and session management for PoundCake."""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import get_db
from api.core.logging import get_logger
from api.schemas.schemas import (
    AuthLoginRequest,
    AuthMeResponse,
    AuthPrincipalResponse,
    AuthProviderResponse,
    AuthRoleBindingCreate,
    AuthRoleBindingResponse,
    AuthRoleBindingUpdate,
    DeleteResponse,
    DeviceAuthorizationPollRequest,
    DeviceAuthorizationPollResponse,
    DeviceAuthorizationStartResponse,
    SessionResponse,
)
from api.services.auth_service import (
    AccessDeniedError,
    AuthContext,
    DeviceAuthorizationExpired,
    DeviceAuthorizationPending,
    InvalidCredentialsError,
    auth0_browser_login_enabled,
    auth0_device_login_enabled,
    authenticate_auth0_authorization_code,
    authenticate_auth0_device_code,
    authenticate_password_provider,
    build_auth_callback_url,
    build_login_context,
    create_role_binding,
    delete_role_binding,
    ensure_request_authorized,
    get_enabled_provider_metadata,
    get_auth0_authorize_url,
    get_principal_by_id,
    get_role_binding,
    get_session_store,
    is_authorized_for_role,
    is_request_public,
    list_principals,
    list_role_bindings,
    rehydrate_session_context,
    service_token_context,
    start_auth0_device_authorization,
    update_role_binding,
)

logger = get_logger(__name__)
router = APIRouter()


def _request_is_secure(request: Request) -> bool:
    """Determine if request should receive a Secure cookie."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        first = forwarded_proto.split(",", 1)[0].strip().lower()
        if first:
            return first == "https"
    return request.url.scheme.lower() == "https"


def _set_session_cookie(request: Request, response: Response, session_id: str) -> None:
    response.set_cookie(
        key="session_token",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=_request_is_secure(request),
        path="/",
        max_age=get_settings().auth_session_timeout,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key="session_token", path="/")


def _normalize_next_target(target: str | None) -> str:
    if not target or not target.startswith("/"):
        return "/overview"
    if target == "/login" or target.startswith("/login?"):
        return "/overview"
    return target


def _session_response(context: AuthContext) -> SessionResponse:
    return SessionResponse(
        session_id=str(context.session_id or ""),
        username=context.username,
        expires_at=str(context.expires_at or ""),
        provider=context.provider,
        role=context.role,
        display_name=context.display_name,
        is_superuser=context.is_superuser,
        permissions=context.permissions,
        token_type="Bearer",
    )


def _principal_response(principal: Any) -> AuthPrincipalResponse:
    return AuthPrincipalResponse(
        id=principal.id,
        provider=principal.provider,
        subject_id=principal.subject_id,
        username=principal.username,
        display_name=principal.display_name,
        principal_type=principal.principal_type,
        groups=list(principal.groups_json or []),
        last_seen_at=principal.last_seen_at,
        created_at=principal.created_at,
        updated_at=principal.updated_at,
    )


def _binding_response(binding: Any) -> AuthRoleBindingResponse:
    return AuthRoleBindingResponse(
        id=binding.id,
        provider=binding.provider,
        binding_type=binding.binding_type,
        role=binding.role,
        principal_id=binding.principal_id,
        external_group=binding.external_group,
        created_by=binding.created_by,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
        principal=(None if binding.principal is None else _principal_response(binding.principal)),
    )


async def _persist_session(
    request: Request, response: Response, context: AuthContext
) -> SessionResponse:
    store = get_session_store()
    stored = await store.create_session(
        context,
        ttl_seconds=get_settings().auth_session_timeout,
    )
    if not stored.session_id:
        raise HTTPException(status_code=500, detail="Could not create session")
    _set_session_cookie(request, response, stored.session_id)
    return _session_response(stored)


async def require_auth_if_enabled(
    request: Request,
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthContext | None:
    """Global dependency that authenticates and authorizes API requests."""
    if os.getenv("TESTING", "").strip().lower() in {"1", "true", "yes"}:
        return None

    settings = get_settings()
    if settings.testing or not settings.auth_enabled:
        return None

    existing = getattr(request.state, "auth_context", None)
    if isinstance(existing, AuthContext):
        return existing

    if is_request_public(request.url.path, request.method):
        return None

    context: AuthContext | None = None
    bearer_value = request.headers.get("Authorization", "")
    service_token = request.headers.get("X-Auth-Token")
    if not service_token and bearer_value.lower().startswith("bearer "):
        service_token = bearer_value[7:].strip()

    if settings.auth_service_token and service_token:
        if secrets.compare_digest(service_token, settings.auth_service_token):
            context = service_token_context()

    if context is None:
        context, resolution_error = await rehydrate_session_context(db, session_token)
        if context is None:
            if resolution_error:
                raise HTTPException(status_code=403, detail=resolution_error)
            if "text/html" in request.headers.get("accept", ""):
                raise HTTPException(
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                    headers={"Location": "/login"},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid session required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if request.url.path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
        if not context.is_human():
            raise HTTPException(status_code=403, detail="Service tokens cannot use this endpoint")

    try:
        ensure_request_authorized(context, request.url.path, request.method)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    request.state.auth_context = context
    return context


async def require_reader(
    context: AuthContext | None = Depends(require_auth_if_enabled),
) -> AuthContext:
    if context is None or not is_authorized_for_role(context, "reader"):
        raise HTTPException(status_code=403, detail="Reader access required")
    return context


async def require_operator(
    context: AuthContext | None = Depends(require_auth_if_enabled),
) -> AuthContext:
    if context is None or not is_authorized_for_role(context, "operator"):
        raise HTTPException(status_code=403, detail="Operator access required")
    return context


async def require_admin(
    context: AuthContext | None = Depends(require_auth_if_enabled),
) -> AuthContext:
    if context is None or not is_authorized_for_role(context, "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return context


async def require_service(
    context: AuthContext | None = Depends(require_auth_if_enabled),
) -> AuthContext:
    if context is None or context.role != "service":
        raise HTTPException(status_code=403, detail="Service access required")
    return context


@router.get("/auth/providers", response_model=list[AuthProviderResponse])
async def get_auth_providers() -> list[AuthProviderResponse]:
    """Return enabled auth provider metadata for UI and CLI discovery."""
    return [AuthProviderResponse.model_validate(item) for item in get_enabled_provider_metadata()]


@router.post("/auth/login", response_model=SessionResponse)
async def login(
    request: Request,
    payload: AuthLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Log in with a password-based provider and set a session cookie."""
    req_id = getattr(request.state, "req_id", "AUTH-LOGIN")
    metadata = get_enabled_provider_metadata()
    password_providers = [str(item["name"]) for item in metadata if item.get("password_login")]
    provider = str(payload.provider or "").strip().lower()
    if not provider:
        if len(password_providers) == 1:
            provider = password_providers[0]
        else:
            raise HTTPException(status_code=400, detail="provider is required")

    logger.info(
        "Login attempt",
        extra={"req_id": req_id, "provider": provider, "username": payload.username},
    )

    try:
        identity = await authenticate_password_provider(
            provider, payload.username, payload.password
        )
        context = await build_login_context(db, identity)
        await db.commit()
        return await _persist_session(request, response, context)
    except InvalidCredentialsError as exc:
        await db.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.error("Login failed", extra={"req_id": req_id, "error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me(
    context: AuthContext = Depends(require_auth_if_enabled),
) -> AuthMeResponse:
    """Return the resolved principal behind the current session."""
    return AuthMeResponse(
        username=context.username,
        display_name=context.display_name,
        provider=context.provider,
        role=context.role,
        principal_type=context.principal_type,
        principal_id=context.principal_id,
        is_superuser=context.is_superuser,
        permissions=context.permissions,
        groups=context.groups,
        expires_at=context.expires_at,
    )


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
) -> dict[str, str]:
    """Destroy the current session."""
    session_token = request.cookies.get("session_token")
    await get_session_store().delete_session(session_token)
    _clear_session_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/auth/oidc/login")
async def oidc_login(
    request: Request,
    next: str = Query(default="/overview"),
) -> RedirectResponse:
    """Start the Auth0 browser login flow."""
    if not auth0_browser_login_enabled():
        raise HTTPException(status_code=404, detail="Auth0 browser login is not enabled")
    state = secrets.token_urlsafe(24)
    target = _normalize_next_target(next)
    callback_url = build_auth_callback_url(str(request.base_url).rstrip("/"))
    store = get_session_store()
    await store.put_state(
        "oidc_state",
        state,
        {"next": target},
        ttl_seconds=get_settings().auth_oidc_state_ttl,
    )
    return RedirectResponse(
        url=await get_auth0_authorize_url(state, callback_url),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/auth/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Complete the Auth0 browser login flow and redirect back to the UI."""
    store = get_session_store()
    state_payload = await store.pop_state("oidc_state", state)
    if not state_payload:
        raise HTTPException(status_code=400, detail="Invalid or expired login state")

    callback_url = build_auth_callback_url(str(request.base_url).rstrip("/"))
    try:
        identity = await authenticate_auth0_authorization_code(code, callback_url)
        context = await build_login_context(db, identity)
        await db.commit()
    except InvalidCredentialsError as exc:
        await db.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    redirect = RedirectResponse(
        url=_normalize_next_target(str(state_payload.get("next") or "/overview")),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    session_response = await _persist_session(request, redirect, context)
    if not session_response.session_id:
        raise HTTPException(status_code=500, detail="Could not create session")
    return redirect


@router.post("/auth/device/start", response_model=DeviceAuthorizationStartResponse)
async def device_start() -> DeviceAuthorizationStartResponse:
    """Start an Auth0 device login flow for CLI users."""
    if not auth0_device_login_enabled():
        raise HTTPException(status_code=404, detail="Auth0 CLI device login is not enabled")
    result = await start_auth0_device_authorization()
    return DeviceAuthorizationStartResponse(
        device_code=result.device_code,
        user_code=result.user_code,
        verification_uri=result.verification_uri,
        verification_uri_complete=result.verification_uri_complete,
        expires_in=result.expires_in,
        interval=result.interval,
    )


@router.post("/auth/device/poll", response_model=DeviceAuthorizationPollResponse)
async def device_poll(
    request: Request,
    payload: DeviceAuthorizationPollRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> DeviceAuthorizationPollResponse:
    """Poll an Auth0 device flow until the user approves it."""
    if payload.provider != "auth0":
        raise HTTPException(status_code=400, detail="Only auth0 supports device login")
    try:
        identity = await authenticate_auth0_device_code(payload.device_code)
        context = await build_login_context(db, identity)
        await db.commit()
        session = await _persist_session(request, response, context)
        return DeviceAuthorizationPollResponse(status="authorized", session=session)
    except DeviceAuthorizationPending:
        await db.rollback()
        return DeviceAuthorizationPollResponse(status="pending", interval=5)
    except DeviceAuthorizationExpired as exc:
        await db.rollback()
        return DeviceAuthorizationPollResponse(status="expired", detail=str(exc))
    except InvalidCredentialsError as exc:
        await db.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/auth/principals", response_model=list[AuthPrincipalResponse])
async def get_principals(
    provider: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _context: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AuthPrincipalResponse]:
    """List observed principals for access management."""
    principals = await list_principals(
        db,
        provider=provider,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [_principal_response(principal) for principal in principals]


@router.get("/auth/bindings", response_model=list[AuthRoleBindingResponse])
async def get_bindings(
    provider: str | None = Query(default=None),
    _context: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AuthRoleBindingResponse]:
    """List configured RBAC bindings."""
    bindings = await list_role_bindings(db, provider=provider)
    return [_binding_response(binding) for binding in bindings]


@router.post("/auth/bindings", response_model=AuthRoleBindingResponse, status_code=201)
async def create_binding(
    payload: AuthRoleBindingCreate,
    context: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuthRoleBindingResponse:
    """Create a new RBAC binding."""
    if payload.provider not in {"auth0", "active_directory"}:
        raise HTTPException(
            status_code=400, detail="Bindings are only supported for Auth0 and Active Directory"
        )
    if payload.binding_type == "user":
        principal = await get_principal_by_id(db, int(payload.principal_id or 0))
        if principal is None:
            raise HTTPException(status_code=404, detail="Principal not found")
        if principal.provider != payload.provider:
            raise HTTPException(
                status_code=400, detail="Principal provider does not match binding provider"
            )

    binding = await create_role_binding(
        db,
        provider=payload.provider,
        binding_type=payload.binding_type,
        role=payload.role,
        principal_id=payload.principal_id,
        external_group=payload.external_group,
        created_by=payload.created_by or context.username,
    )
    await db.commit()
    await db.refresh(binding)
    if binding.principal_id:
        binding.principal = await get_principal_by_id(db, binding.principal_id)
    return _binding_response(binding)


@router.patch("/auth/bindings/{binding_id}", response_model=AuthRoleBindingResponse)
async def update_binding(
    binding_id: int,
    payload: AuthRoleBindingUpdate,
    _context: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuthRoleBindingResponse:
    """Update an existing RBAC binding."""
    binding = await get_role_binding(db, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    binding = await update_role_binding(
        db,
        binding,
        role=payload.role,
        external_group=payload.external_group,
    )
    await db.commit()
    await db.refresh(binding)
    if binding.principal_id:
        binding.principal = await get_principal_by_id(db, binding.principal_id)
    return _binding_response(binding)


@router.delete("/auth/bindings/{binding_id}", response_model=DeleteResponse)
async def delete_binding(
    binding_id: int,
    _context: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DeleteResponse:
    """Delete an RBAC binding."""
    binding = await get_role_binding(db, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    await delete_role_binding(db, binding)
    await db.commit()
    return DeleteResponse(id=binding_id, message="Binding deleted")

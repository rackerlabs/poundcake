"""Bakery monitor registration, route sync, and heartbeat helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.core.config import get_settings
from api.core.database import SessionLocal
from api.core.http_client import request_with_retry
from api.core.logging import get_logger
from api.models.models import BakeryMonitorState, Recipe, RecipeIngredient
from api.services.bakery_secret_store import decrypt_secret, encrypt_secret
from api.services.communications_policy import (
    POLICY_METADATA_KEY,
    CommunicationRoute,
    get_global_policy_routes,
    get_recipe_local_routes,
    is_hidden_workflow_recipe,
)
from shared.bakery_contract import (
    MonitorHeartbeatRequest,
    MonitorHeartbeatResponse,
    MonitorRegistrationRequest,
    MonitorRegistrationResponse,
    MonitorRouteCatalogEntry,
    MonitorRouteCatalogSyncRequest,
    MonitorRouteCatalogSyncResponse,
)
from shared.hmac import build_hmac_signing_payload, canonical_json_body, hmac_sha256_hex

logger = get_logger(__name__)

_REGISTER_LOCK = asyncio.Lock()
_ROUTE_SYNC_LOCK = asyncio.Lock()
_HEARTBEAT_TASK: asyncio.Task[None] | None = None

ROUTE_VALIDATION_BYPASS_SOURCES = {"poundcake_system"}
SCOPE_SORT_ORDER = {"global": 0, "fallback": 1, "recipe": 2}


@dataclass(slots=True)
class MonitorCredentials:
    monitor_id: str
    monitor_uuid: str
    hmac_key_id: str
    hmac_secret: str
    route_sync_dirty: bool
    last_route_catalog_hash: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_body(payload: dict[str, Any] | None) -> str:
    return canonical_json_body(payload)


def _monitor_id() -> str:
    monitor_id = str(get_settings().bakery_monitor_id or "").strip()
    if not monitor_id:
        raise RuntimeError("POUNDCAKE_BAKERY_MONITOR_ID is required for Bakery monitor auth")
    return monitor_id


def monitor_auth_enabled() -> bool:
    settings = get_settings()
    return (
        bool(settings.bakery_enabled)
        and settings.bakery_auth_mode.lower() == "hmac"
        and bool(str(settings.bakery_base_url or "").strip())
        and bool(str(settings.bakery_monitor_id or "").strip())
    )


def _catalog_hash(routes: list[MonitorRouteCatalogEntry]) -> str:
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in routes],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state_to_credentials(state: BakeryMonitorState | None) -> MonitorCredentials | None:
    if state is None:
        return None
    if not state.monitor_uuid or not state.hmac_key_id or not state.encrypted_hmac_secret:
        return None
    return MonitorCredentials(
        monitor_id=state.monitor_id,
        monitor_uuid=state.monitor_uuid,
        hmac_key_id=state.hmac_key_id,
        hmac_secret=decrypt_secret(state.encrypted_hmac_secret),
        route_sync_dirty=bool(state.route_sync_dirty),
        last_route_catalog_hash=state.last_route_catalog_hash,
    )


def _request_headers(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    key_id: str,
    secret: str,
    monitor_uuid: str | None = None,
) -> dict[str, str]:
    body = _canonical_body(payload)
    timestamp = str(int(time.time()))
    signing_payload = build_hmac_signing_payload(
        timestamp=timestamp,
        method=method,
        path=path,
        body=body.encode("utf-8"),
    )
    digest = hmac_sha256_hex(secret, signing_payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"HMAC {key_id}:{digest}",
        "X-Timestamp": timestamp,
    }
    if monitor_uuid:
        headers["X-Bakery-Monitor-UUID"] = monitor_uuid
    return headers


def _is_unauthorized(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401


async def _request_json(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.bakery_base_url.rstrip('/')}{path}"
    body = _canonical_body(payload)
    response = await request_with_retry(
        method,
        url,
        headers=headers,
        content=body.encode("utf-8") if body else None,
        timeout=settings.bakery_request_timeout_seconds,
        retries=settings.bakery_max_retries,
    )
    response.raise_for_status()
    return response.json()


async def _load_monitor_state(
    db: AsyncSession,
    *,
    for_update: bool = False,
) -> BakeryMonitorState | None:
    query = select(BakeryMonitorState).where(BakeryMonitorState.monitor_id == _monitor_id())
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalars().first()


async def _get_or_create_monitor_state(
    db: AsyncSession,
    *,
    for_update: bool = False,
) -> BakeryMonitorState:
    state = await _load_monitor_state(db, for_update=for_update)
    if state is not None:
        return state
    now = _now()
    state = BakeryMonitorState(
        monitor_id=_monitor_id(),
        installation_id=get_settings().instance_id,
        route_sync_dirty=True,
        created_at=now,
        updated_at=now,
    )
    db.add(state)
    await db.flush()
    return state


def _route_entry(
    *,
    scope: str,
    owner_key: str,
    route: CommunicationRoute,
    outage_enabled: bool,
) -> MonitorRouteCatalogEntry:
    return MonitorRouteCatalogEntry(
        scope=scope,
        owner_key=owner_key,
        route_id=route.id,
        label=route.label,
        execution_target=route.execution_target,
        destination_target=route.destination_target or "",
        provider_config=route.provider_config or {},
        enabled=route.enabled,
        outage_enabled=outage_enabled,
        position=route.position,
    )


async def build_monitor_route_catalog(db: AsyncSession) -> list[MonitorRouteCatalogEntry]:
    entries: list[MonitorRouteCatalogEntry] = []
    global_routes = await get_global_policy_routes(db)
    for route in global_routes:
        entries.append(
            _route_entry(
                scope="global",
                owner_key="global",
                route=route,
                outage_enabled=bool(route.enabled),
            )
        )
        if route.enabled:
            entries.append(
                _route_entry(
                    scope="fallback",
                    owner_key="fallback",
                    route=route,
                    outage_enabled=False,
                )
            )

    result = await db.execute(
        select(Recipe)
        .options(joinedload(Recipe.recipe_ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.deleted.is_(False))
    )
    recipes = result.unique().scalars().all()
    for recipe in recipes:
        if is_hidden_workflow_recipe(recipe):
            continue
        for route in get_recipe_local_routes(recipe):
            entries.append(
                _route_entry(
                    scope="recipe",
                    owner_key=str(recipe.id),
                    route=route,
                    outage_enabled=False,
                )
            )

    entries.sort(
        key=lambda item: (
            SCOPE_SORT_ORDER.get(item.scope, 9),
            item.owner_key,
            item.position,
            item.label.lower(),
            item.route_id,
        )
    )
    return entries


def monitor_route_validation_required(payload: dict[str, Any]) -> bool:
    context = payload.get("context")
    context_map = context if isinstance(context, dict) else {}
    source = str(context_map.get("source") or payload.get("source") or "poundcake").strip().lower()
    return source not in ROUTE_VALIDATION_BYPASS_SOURCES


def _route_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context")
    context_map = context if isinstance(context, dict) else {}
    metadata = context_map.get(POLICY_METADATA_KEY)
    if isinstance(metadata, dict):
        return dict(metadata)
    direct = {
        "scope": context_map.get("scope"),
        "owner_key": context_map.get("owner_key"),
        "route_id": context_map.get("route_id"),
        "label": context_map.get("route_label"),
        "execution_target": context_map.get("execution_target") or context_map.get("provider_type"),
        "destination_target": context_map.get("destination_target"),
        "provider_config": context_map.get("provider_config"),
    }
    if all(str(direct.get(key) or "").strip() for key in ("scope", "owner_key", "route_id")):
        return direct
    return {}


async def prepare_managed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not monitor_route_validation_required(payload):
        return payload

    metadata = _route_metadata_from_payload(payload)
    if not metadata:
        raise ValueError(
            "Managed PoundCake Bakery requests must include route metadata in context."
        )

    async with SessionLocal() as db:
        routes = await build_monitor_route_catalog(db)

    lookup = {(item.scope, item.owner_key, item.route_id): item for item in routes}
    route = lookup.get(
        (
            str(metadata.get("scope") or "").strip(),
            str(metadata.get("owner_key") or "").strip(),
            str(metadata.get("route_id") or "").strip(),
        )
    )
    if route is None:
        raise ValueError("Bakery request route is not part of the current monitor route catalog.")

    execution_target = str(
        metadata.get("execution_target") or payload.get("provider_type") or ""
    ).strip()
    if execution_target and execution_target != route.execution_target:
        raise ValueError("Bakery request execution_target does not match the registered route.")

    destination_target = str(metadata.get("destination_target") or "").strip()
    if destination_target and destination_target != (route.destination_target or ""):
        raise ValueError("Bakery request destination_target does not match the registered route.")

    provider_config = metadata.get("provider_config")
    if isinstance(provider_config, dict) and provider_config != (route.provider_config or {}):
        raise ValueError("Bakery request provider_config does not match the registered route.")

    context = payload.get("context")
    context_map = dict(context) if isinstance(context, dict) else {}
    canonical_route = route.model_dump(mode="json")
    context_map.update(
        {
            "scope": route.scope,
            "owner_key": route.owner_key,
            "route_id": route.route_id,
            "route_label": route.label,
            "provider_type": route.execution_target,
            "execution_target": route.execution_target,
            "destination_target": route.destination_target,
            "provider_config": route.provider_config or {},
            POLICY_METADATA_KEY: canonical_route,
        }
    )
    normalized = dict(payload)
    normalized["context"] = context_map
    normalized.setdefault("source", "poundcake")
    return normalized


async def ensure_monitor_registered(*, force: bool = False) -> MonitorCredentials:
    async with _REGISTER_LOCK:
        async with SessionLocal() as db:
            async with db.begin():
                state = await _get_or_create_monitor_state(db, for_update=True)
                credentials = _state_to_credentials(state)
                if credentials is not None and not force:
                    return credentials

                settings = get_settings()
                if not settings.bakery_bootstrap_hmac_key_id or not settings.bakery_bootstrap_hmac_key:
                    raise RuntimeError(
                        "POUNDCAKE_BAKERY_BOOTSTRAP_HMAC_KEY_ID and "
                        "POUNDCAKE_BAKERY_BOOTSTRAP_HMAC_KEY are required for Bakery registration"
                    )

                request_model = MonitorRegistrationRequest(
                    monitor_id=_monitor_id(),
                    installation_id=settings.instance_id,
                    app_version=settings.app_version,
                )
                request_payload = request_model.model_dump(mode="json", exclude_none=True)
                headers = _request_headers(
                    method="POST",
                    path="/api/v1/monitors/register",
                    payload=request_payload,
                    key_id=settings.bakery_bootstrap_hmac_key_id,
                    secret=settings.bakery_bootstrap_hmac_key,
                )
                response_payload = await _request_json(
                    method="POST",
                    path="/api/v1/monitors/register",
                    payload=request_payload,
                    headers=headers,
                )
                response = MonitorRegistrationResponse.model_validate(response_payload)

                state.monitor_uuid = response.monitor_uuid
                state.hmac_key_id = response.hmac_key_id
                state.encrypted_hmac_secret = encrypt_secret(response.hmac_secret)
                state.installation_id = settings.instance_id
                state.route_sync_dirty = True
                state.updated_at = _now()
                await db.flush()
                return MonitorCredentials(
                    monitor_id=response.monitor_id,
                    monitor_uuid=response.monitor_uuid,
                    hmac_key_id=response.hmac_key_id,
                    hmac_secret=response.hmac_secret,
                    route_sync_dirty=True,
                    last_route_catalog_hash=state.last_route_catalog_hash,
                )


async def build_monitor_auth_headers(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
) -> dict[str, str]:
    credentials = await ensure_monitor_registered()
    return _request_headers(
        method=method,
        path=path,
        payload=payload,
        key_id=credentials.hmac_key_id,
        secret=credentials.hmac_secret,
        monitor_uuid=credentials.monitor_uuid,
    )


async def mark_route_catalog_dirty() -> None:
    if not monitor_auth_enabled():
        return
    async with SessionLocal() as db:
        async with db.begin():
            state = await _load_monitor_state(db, for_update=True)
            if state is None:
                return
            state.route_sync_dirty = True
            state.updated_at = _now()
            await db.flush()


async def sync_monitor_route_catalog(*, force: bool = False) -> MonitorRouteCatalogSyncResponse | None:
    if not monitor_auth_enabled():
        return None
    async with _ROUTE_SYNC_LOCK:
        credentials = await ensure_monitor_registered()
        async with SessionLocal() as db:
            routes = await build_monitor_route_catalog(db)
        catalog_hash = _catalog_hash(routes)

        async with SessionLocal() as db:
            async with db.begin():
                state = await _get_or_create_monitor_state(db, for_update=True)
                should_sync = force or bool(state.route_sync_dirty)
                if state.last_route_catalog_hash != catalog_hash:
                    should_sync = True
                if not should_sync:
                    return None

                request_model = MonitorRouteCatalogSyncRequest(
                    catalog_hash=catalog_hash,
                    routes=routes,
                )
                request_payload = request_model.model_dump(mode="json")
                headers = _request_headers(
                    method="PUT",
                    path="/api/v1/monitors/self/routes",
                    payload=request_payload,
                    key_id=credentials.hmac_key_id,
                    secret=credentials.hmac_secret,
                    monitor_uuid=credentials.monitor_uuid,
                )
                try:
                    response_payload = await _request_json(
                        method="PUT",
                        path="/api/v1/monitors/self/routes",
                        payload=request_payload,
                        headers=headers,
                    )
                except Exception as exc:  # noqa: BLE001
                    if not _is_unauthorized(exc):
                        raise
                    credentials = await ensure_monitor_registered(force=True)
                    headers = _request_headers(
                        method="PUT",
                        path="/api/v1/monitors/self/routes",
                        payload=request_payload,
                        key_id=credentials.hmac_key_id,
                        secret=credentials.hmac_secret,
                        monitor_uuid=credentials.monitor_uuid,
                    )
                    response_payload = await _request_json(
                        method="PUT",
                        path="/api/v1/monitors/self/routes",
                        payload=request_payload,
                        headers=headers,
                    )
                response = MonitorRouteCatalogSyncResponse.model_validate(response_payload)
                state.last_route_catalog_hash = response.catalog_hash
                state.route_sync_dirty = False
                state.updated_at = _now()
                await db.flush()
                return response


async def ensure_monitor_route_catalog_current() -> str:
    if not monitor_auth_enabled():
        return ""
    async with SessionLocal() as db:
        routes = await build_monitor_route_catalog(db)
    catalog_hash = _catalog_hash(routes)

    async with SessionLocal() as db:
        state = await _load_monitor_state(db)
        if state is None:
            await sync_monitor_route_catalog(force=True)
            return catalog_hash
        if state.route_sync_dirty or state.last_route_catalog_hash != catalog_hash:
            await sync_monitor_route_catalog(force=True)
    return catalog_hash


async def heartbeat_once() -> MonitorHeartbeatResponse:
    settings = get_settings()
    credentials = await ensure_monitor_registered()
    catalog_hash = await ensure_monitor_route_catalog_current()

    request_model = MonitorHeartbeatRequest(
        catalog_hash=catalog_hash,
        installation_id=settings.instance_id,
        app_version=settings.app_version,
        details={"instance_id": settings.instance_id},
    )
    request_payload = request_model.model_dump(mode="json", exclude_none=True)
    headers = _request_headers(
        method="POST",
        path="/api/v1/monitors/heartbeat",
        payload=request_payload,
        key_id=credentials.hmac_key_id,
        secret=credentials.hmac_secret,
        monitor_uuid=credentials.monitor_uuid,
    )
    try:
        response_payload = await _request_json(
            method="POST",
            path="/api/v1/monitors/heartbeat",
            payload=request_payload,
            headers=headers,
        )
    except Exception as exc:  # noqa: BLE001
        if not _is_unauthorized(exc):
            raise
        credentials = await ensure_monitor_registered(force=True)
        headers = _request_headers(
            method="POST",
            path="/api/v1/monitors/heartbeat",
            payload=request_payload,
            key_id=credentials.hmac_key_id,
            secret=credentials.hmac_secret,
            monitor_uuid=credentials.monitor_uuid,
        )
        response_payload = await _request_json(
            method="POST",
            path="/api/v1/monitors/heartbeat",
            payload=request_payload,
            headers=headers,
        )
    response = MonitorHeartbeatResponse.model_validate(response_payload)

    async with SessionLocal() as db:
        async with db.begin():
            state = await _get_or_create_monitor_state(db, for_update=True)
            state.last_heartbeat_status = response.status
            state.last_heartbeat_at = _now()
            state.updated_at = _now()
            await db.flush()

    if response.route_sync_required:
        await sync_monitor_route_catalog(force=True)
    return response


async def reregister_monitor() -> MonitorCredentials:
    credentials = await ensure_monitor_registered(force=True)
    await sync_monitor_route_catalog(force=True)
    return credentials


async def _heartbeat_loop() -> None:
    settings = get_settings()
    interval = max(int(settings.bakery_monitor_heartbeat_interval_seconds or 30), 5)
    while True:
        try:
            response = await heartbeat_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Bakery monitor heartbeat failed",
                extra={"error": str(exc), "monitor_id": settings.bakery_monitor_id},
            )
        else:
            interval = max(int(response.heartbeat_interval_sec or interval), 5)
        await asyncio.sleep(interval)


async def start_bakery_monitor_heartbeat() -> None:
    global _HEARTBEAT_TASK
    settings = get_settings()
    if not monitor_auth_enabled():
        return
    if _HEARTBEAT_TASK is not None and not _HEARTBEAT_TASK.done():
        return
    try:
        await heartbeat_once()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Initial Bakery monitor heartbeat failed",
            extra={"error": str(exc), "monitor_id": settings.bakery_monitor_id},
        )
    _HEARTBEAT_TASK = asyncio.create_task(_heartbeat_loop(), name="bakery-monitor-heartbeat")


async def stop_bakery_monitor_heartbeat() -> None:
    global _HEARTBEAT_TASK
    if _HEARTBEAT_TASK is None:
        return
    _HEARTBEAT_TASK.cancel()
    try:
        await _HEARTBEAT_TASK
    except asyncio.CancelledError:
        pass
    _HEARTBEAT_TASK = None

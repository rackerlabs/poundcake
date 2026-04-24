"""Release update advisory detection and notification delivery."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.config import get_settings
from api.core.database import SessionLocal
from api.core.http_client import request_with_retry
from api.core.logging import get_logger
from api.core.metrics import record_release_update_check, record_release_update_notification
from api.models.models import (
    ReleaseUpdateNotification,
    ReleaseUpdateNotificationDelivery,
)
from api.services.bakery_client import open_communication_with_key, poll_operation
from api.services.communications_policy import (
    POLICY_METADATA_KEY,
    get_global_policy_routes,
)

logger = get_logger(__name__)

OCI_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
OCI_CHART_CONFIG_MEDIA_TYPE = "application/vnd.cncf.helm.config.v1+json"
SYSTEM_SOURCE = "poundcake_system"
NOTIFIED_STATE = "notified"
SUCCEEDED_DELIVERY_STATE = "succeeded"
RETRYABLE_DELIVERY_STATES = {"pending", "failed", "sending"}

_CHECK_LOCK = asyncio.Lock()
_CHECKER_TASK: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class VersionKey:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]


@dataclass(frozen=True)
class OciRepositoryRef:
    registry: str
    repository: str


@dataclass(frozen=True)
class OciChartRelease:
    chart_version: str
    app_version: str
    created_at: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_version(value: str | None) -> VersionKey | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw[1:] if raw.startswith("v") else raw
    without_build = raw.split("+", 1)[0]
    core, prerelease = without_build.split("-", 1) if "-" in without_build else (without_build, "")
    parts = core.split(".")
    if len(parts) > 3 or any(not part.isdigit() for part in parts):
        return None
    padded = [int(part) for part in parts] + [0] * (3 - len(parts))
    prerelease_parts = tuple(part for part in re.split(r"[.-]", prerelease) if part)
    return VersionKey(padded[0], padded[1], padded[2], prerelease_parts)


def _compare_identifier(left: str, right: str) -> int:
    left_numeric = left.isdigit()
    right_numeric = right.isdigit()
    if left_numeric and right_numeric:
        left_int = int(left)
        right_int = int(right)
        return (left_int > right_int) - (left_int < right_int)
    if left_numeric != right_numeric:
        return -1 if left_numeric else 1
    return (left > right) - (left < right)


def compare_versions(left: str | None, right: str | None) -> int:
    """Compare semver-ish version strings; invalid values sort lower than valid ones."""
    left_key = _parse_version(left)
    right_key = _parse_version(right)
    if left_key is None and right_key is None:
        return 0
    if left_key is None:
        return -1
    if right_key is None:
        return 1
    left_core = (left_key.major, left_key.minor, left_key.patch)
    right_core = (right_key.major, right_key.minor, right_key.patch)
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)
    if not left_key.prerelease and right_key.prerelease:
        return 1
    if left_key.prerelease and not right_key.prerelease:
        return -1
    for left_part, right_part in zip(left_key.prerelease, right_key.prerelease):
        comparison = _compare_identifier(left_part, right_part)
        if comparison:
            return comparison
    return (len(left_key.prerelease) > len(right_key.prerelease)) - (
        len(left_key.prerelease) < len(right_key.prerelease)
    )


def is_prerelease(value: str | None) -> bool:
    key = _parse_version(value)
    return bool(key and key.prerelease)


def is_release_newer(
    release: OciChartRelease,
    *,
    current_app_version: str,
    current_chart_version: str,
) -> bool:
    app_comparison = compare_versions(release.app_version, current_app_version)
    if app_comparison > 0:
        return True
    if app_comparison < 0:
        return False
    if not current_chart_version:
        return False
    return compare_versions(release.chart_version, current_chart_version) > 0


def _sortable_version(value: str) -> tuple[int, int, int, int, tuple[str, ...]]:
    key = _parse_version(value) or VersionKey(0, 0, 0, ("invalid",))
    return (key.major, key.minor, key.patch, 0 if key.prerelease else 1, key.prerelease)


def _release_sort_key(
    release: OciChartRelease,
) -> tuple[tuple[int, int, int, int, tuple[str, ...]], tuple[int, int, int, int, tuple[str, ...]]]:
    return _sortable_version(release.app_version), _sortable_version(release.chart_version)


def parse_oci_repository(value: str) -> OciRepositoryRef:
    raw = str(value or "").strip()
    if not raw.startswith("oci://"):
        raise ValueError("release update OCI repository must start with oci://")
    stripped = raw.removeprefix("oci://").strip("/")
    registry, _, repository = stripped.partition("/")
    if not registry or not repository:
        raise ValueError("release update OCI repository must include registry and repository")
    return OciRepositoryRef(registry=registry, repository=repository)


def _parse_www_authenticate(value: str | None) -> tuple[str, dict[str, str]]:
    raw = str(value or "").strip()
    if not raw:
        return "", {}
    scheme, _, rest = raw.partition(" ")
    items = {
        key: parsed_value for key, parsed_value in re.findall(r'([A-Za-z0-9_]+)="([^"]*)"', rest)
    }
    return scheme.lower(), items


def _parse_link_next(value: str | None) -> str | None:
    raw = str(value or "")
    for part in raw.split(","):
        match = re.search(r"<([^>]+)>;\s*rel=\"next\"", part.strip())
        if match:
            return match.group(1)
    return None


def _merge_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_registry_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class OciChartClient:
    """Small OCI registry client for Helm chart metadata."""

    def __init__(
        self,
        *,
        oci_repository: str,
        registry_username: str = "",
        registry_password: str = "",
        registry_token: str = "",
    ) -> None:
        self.oci_repository = oci_repository
        self.ref = parse_oci_repository(oci_repository)
        self.registry_username = registry_username
        self.registry_password = registry_password
        self.registry_token = registry_token
        self._bearer_token: str | None = None

    @property
    def _base_url(self) -> str:
        return f"https://{self.ref.registry}/v2/{self.ref.repository}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        if self._bearer_token:
            request_headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self.registry_token:
            request_headers["Authorization"] = f"Bearer {self.registry_token}"

        response = await request_with_retry(
            method,
            url,
            headers=request_headers,
            timeout=15,
            retries=2,
        )
        if response.status_code == 401 and retry_auth:
            token = await self._fetch_bearer_token(response.headers.get("www-authenticate"))
            if token:
                self._bearer_token = token
                return await self._request(method, url, headers=headers, retry_auth=False)
        response.raise_for_status()
        return response

    async def _fetch_bearer_token(self, challenge: str | None) -> str | None:
        scheme, params = _parse_www_authenticate(challenge)
        if scheme != "bearer" or not params.get("realm"):
            return None

        token_headers: dict[str, str] = {}
        username = self.registry_username.strip()
        password = self.registry_password.strip() or self.registry_token.strip()
        if username or password:
            credential = f"{username or 'token'}:{password}".encode("utf-8")
            token_headers["Authorization"] = "Basic " + base64.b64encode(credential).decode("ascii")

        token_url = _merge_query(
            params["realm"],
            {
                key: value
                for key, value in {
                    "service": params.get("service"),
                    "scope": params.get("scope", f"repository:{self.ref.repository}:pull"),
                }.items()
                if value
            },
        )
        response = await request_with_retry(
            "GET",
            token_url,
            headers=token_headers,
            timeout=15,
            retries=2,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token") or payload.get("access_token")
        return str(token) if token else None

    async def list_tags(self) -> list[str]:
        tags: list[str] = []
        next_url: str | None = f"{self._base_url}/tags/list?n=100"
        while next_url:
            response = await self._request("GET", next_url)
            payload = response.json()
            tags.extend(str(tag) for tag in payload.get("tags") or [])
            link_next = _parse_link_next(response.headers.get("link"))
            if link_next and link_next.startswith("/"):
                next_url = f"https://{self.ref.registry}{link_next}"
            else:
                next_url = link_next
        return tags

    async def get_chart_release(self, tag: str) -> OciChartRelease | None:
        response = await self._request(
            "GET",
            f"{self._base_url}/manifests/{tag}",
            headers={"Accept": OCI_MANIFEST_ACCEPT},
        )
        manifest = response.json()
        config = manifest.get("config") if isinstance(manifest, dict) else {}
        if not isinstance(config, dict) or not config.get("digest"):
            return None
        config_response = await self._request(
            "GET",
            f"{self._base_url}/blobs/{config['digest']}",
            headers={"Accept": OCI_CHART_CONFIG_MEDIA_TYPE},
        )
        chart = config_response.json()
        chart_version = str(chart.get("version") or tag).strip()
        app_version = str(chart.get("appVersion") or "").strip()
        if not chart_version or not app_version:
            return None
        annotations = manifest.get("annotations") if isinstance(manifest, dict) else {}
        created_at = None
        if isinstance(annotations, dict):
            created_at = _parse_registry_datetime(
                annotations.get("org.opencontainers.image.created")
            )
        return OciChartRelease(
            chart_version=chart_version,
            app_version=app_version,
            created_at=created_at,
        )

    async def fetch_latest_release(self, *, include_prereleases: bool) -> OciChartRelease | None:
        releases: list[OciChartRelease] = []
        for tag in await self.list_tags():
            if _parse_version(tag) is None:
                continue
            try:
                release = await self.get_chart_release(tag)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Failed to inspect OCI chart tag",
                    extra={"tag": tag, "oci_repository": self.oci_repository, "error": str(exc)},
                )
                continue
            if release is None:
                continue
            if (
                _parse_version(release.chart_version) is None
                or _parse_version(release.app_version) is None
            ):
                continue
            if not include_prereleases and (
                is_prerelease(release.chart_version) or is_prerelease(release.app_version)
            ):
                continue
            releases.append(release)
        if not releases:
            return None
        return max(releases, key=_release_sort_key)


def _client_from_settings() -> OciChartClient:
    settings = get_settings()
    return OciChartClient(
        oci_repository=settings.release_update_notifications_oci_repository,
        registry_username=settings.release_update_notifications_registry_username,
        registry_password=settings.release_update_notifications_registry_password,
        registry_token=settings.release_update_notifications_registry_token,
    )


async def _load_notification(
    db: AsyncSession,
    *,
    oci_repository: str,
    available_app_version: str,
    available_chart_version: str,
    for_update: bool = False,
) -> ReleaseUpdateNotification | None:
    query = (
        select(ReleaseUpdateNotification)
        .options(selectinload(ReleaseUpdateNotification.deliveries))
        .where(
            ReleaseUpdateNotification.oci_repository == oci_repository,
            ReleaseUpdateNotification.available_app_version == available_app_version,
            ReleaseUpdateNotification.available_chart_version == available_chart_version,
        )
    )
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.unique().scalars().first()


async def _get_or_create_notification(
    db: AsyncSession,
    *,
    release: OciChartRelease,
) -> ReleaseUpdateNotification:
    settings = get_settings()
    oci_repository = settings.release_update_notifications_oci_repository
    existing = await _load_notification(
        db,
        oci_repository=oci_repository,
        available_app_version=release.app_version,
        available_chart_version=release.chart_version,
        for_update=True,
    )
    if existing is not None:
        return existing

    notification = ReleaseUpdateNotification(
        oci_repository=oci_repository,
        current_app_version=settings.app_version,
        current_chart_version=settings.chart_version,
        available_app_version=release.app_version,
        available_chart_version=release.chart_version,
        available_created_at=release.created_at,
        state="pending",
    )
    db.add(notification)
    await db.flush()
    return notification


async def _snapshot_routes_if_needed(
    db: AsyncSession,
    notification: ReleaseUpdateNotification,
) -> list[ReleaseUpdateNotificationDelivery]:
    count = await db.scalar(
        select(func.count(ReleaseUpdateNotificationDelivery.id)).where(
            ReleaseUpdateNotificationDelivery.notification_id == notification.id
        )
    )
    if int(count or 0) > 0:
        return list(notification.deliveries or [])

    routes = [route for route in await get_global_policy_routes(db) if route.enabled]
    if not routes:
        notification.state = "blocked"
        notification.latest_error = "No enabled global communications routes are configured."
        notification.updated_at = _utc_now()
        record_release_update_notification("blocked_no_routes")
        return []

    deliveries: list[ReleaseUpdateNotificationDelivery] = []
    for route in routes:
        delivery = ReleaseUpdateNotificationDelivery(
            notification_id=notification.id,
            route_id=route.id,
            route_label=route.label,
            execution_target=route.execution_target,
            destination_target=route.destination_target or "",
            provider_config=route.provider_config or {},
            state="pending",
        )
        db.add(delivery)
        deliveries.append(delivery)
    notification.deliveries = deliveries
    notification.state = "notifying"
    notification.latest_error = None
    notification.updated_at = _utc_now()
    await db.flush()
    return deliveries


def build_advisory_payload(
    notification: ReleaseUpdateNotification,
    delivery: ReleaseUpdateNotificationDelivery,
) -> dict[str, Any]:
    current_chart = notification.current_chart_version or "unknown"
    available_created = (
        notification.available_created_at.isoformat()
        if notification.available_created_at
        else "unknown"
    )
    description = (
        f"A newer PoundCake release is available.\n\n"
        f"Current app version: {notification.current_app_version}\n"
        f"Current chart version: {current_chart}\n"
        f"Available app version: {notification.available_app_version}\n"
        f"Available chart version: {notification.available_chart_version}\n"
        f"OCI repository: {notification.oci_repository}\n"
        f"Release published: {available_created}\n\n"
        "PoundCake did not perform an automatic upgrade. Review the release and run the "
        "normal install/upgrade process when ready."
    )
    route_metadata = {
        "scope": "global",
        "owner_key": "global",
        "route_id": delivery.route_id,
        "label": delivery.route_label,
        "execution_target": delivery.execution_target,
        "destination_target": delivery.destination_target or "",
        "provider_config": delivery.provider_config or {},
        "enabled": True,
        "outage_enabled": False,
        "position": 0,
    }
    context = {
        "source": SYSTEM_SOURCE,
        "category": "release_update",
        "oci_repository": notification.oci_repository,
        "current_app_version": notification.current_app_version,
        "current_chart_version": notification.current_chart_version,
        "available_app_version": notification.available_app_version,
        "available_chart_version": notification.available_chart_version,
        "release_update_notification_id": notification.id,
        "provider_type": delivery.execution_target,
        "execution_target": delivery.execution_target,
        "destination_target": delivery.destination_target or "",
        "provider_config": delivery.provider_config or {},
        "scope": "global",
        "owner_key": "global",
        "route_id": delivery.route_id,
        "route_label": delivery.route_label,
        POLICY_METADATA_KEY: route_metadata,
    }
    return {
        "title": (f"[PoundCake Update Available] {notification.available_app_version} available"),
        "description": description,
        "message": description,
        "severity": "info",
        "category": "release_update",
        "source": SYSTEM_SOURCE,
        "context": context,
    }


def _idempotency_key(
    notification: ReleaseUpdateNotification,
    delivery: ReleaseUpdateNotificationDelivery,
) -> str:
    seed = (
        "release-update:"
        f"{notification.oci_repository}:"
        f"{notification.available_app_version}:"
        f"{notification.available_chart_version}:"
        f"{delivery.route_id}"
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def _set_delivery_state(
    delivery_id: int,
    *,
    state: str,
    communication_id: str | None = None,
    operation_id: str | None = None,
    error: str | None = None,
) -> None:
    async with SessionLocal() as db:
        async with db.begin():
            delivery = await db.get(ReleaseUpdateNotificationDelivery, delivery_id)
            if delivery is None:
                return
            delivery.state = state
            if communication_id is not None:
                delivery.bakery_communication_id = communication_id
            if operation_id is not None:
                delivery.bakery_operation_id = operation_id
            delivery.last_error = error
            if state == SUCCEEDED_DELIVERY_STATE:
                delivery.delivered_at = _utc_now()
            delivery.updated_at = _utc_now()


async def _deliver_route(
    notification: ReleaseUpdateNotification,
    delivery: ReleaseUpdateNotificationDelivery,
) -> None:
    if delivery.state == SUCCEEDED_DELIVERY_STATE:
        return
    await _set_delivery_state(delivery.id, state="sending")
    payload = build_advisory_payload(notification, delivery)
    try:
        accepted = await open_communication_with_key(
            req_id="SYSTEM-RELEASE-UPDATE",
            payload=payload,
            idempotency_key=_idempotency_key(notification, delivery),
        )
        operation = await poll_operation(accepted.operation_id)
        if operation.status.lower() != "succeeded":
            raise RuntimeError(f"Bakery operation ended in status={operation.status}")
    except Exception as exc:  # noqa: BLE001
        await _set_delivery_state(delivery.id, state="failed", error=str(exc))
        record_release_update_notification("failed")
        logger.warning(
            "Release update advisory delivery failed",
            extra={
                "notification_id": notification.id,
                "delivery_id": delivery.id,
                "route_id": delivery.route_id,
                "error": str(exc),
            },
        )
        return

    await _set_delivery_state(
        delivery.id,
        state=SUCCEEDED_DELIVERY_STATE,
        communication_id=accepted.communication_id,
        operation_id=accepted.operation_id,
    )
    record_release_update_notification("succeeded")


async def _finalize_notification(notification_id: int) -> str:
    async with SessionLocal() as db:
        async with db.begin():
            notification = await db.get(
                ReleaseUpdateNotification,
                notification_id,
                options=[selectinload(ReleaseUpdateNotification.deliveries)],
            )
            if notification is None:
                return "missing"
            deliveries = list(notification.deliveries or [])
            failed = [item for item in deliveries if item.state != SUCCEEDED_DELIVERY_STATE]
            if failed:
                notification.state = "failed"
                notification.latest_error = (
                    f"{len(failed)} release update advisory route(s) are not delivered."
                )
                notification.updated_at = _utc_now()
                return "failed"
            notification.state = NOTIFIED_STATE
            notification.latest_error = None
            notification.notified_at = _utc_now()
            notification.updated_at = _utc_now()
            return NOTIFIED_STATE


async def process_release_notification(release: OciChartRelease) -> str:
    settings = get_settings()
    async with SessionLocal() as db:
        async with db.begin():
            notification = await _get_or_create_notification(db, release=release)
            if notification.state == NOTIFIED_STATE:
                record_release_update_notification("already_notified")
                return NOTIFIED_STATE
            if not settings.bakery_enabled or not settings.bakery_base_url:
                notification.state = "blocked"
                notification.latest_error = "Bakery client is disabled."
                notification.updated_at = _utc_now()
                logger.warning("Release update advisory blocked because Bakery client is disabled")
                record_release_update_notification("blocked_bakery_disabled")
                return "blocked"
            deliveries = await _snapshot_routes_if_needed(db, notification)
            notification_id = notification.id

    if not deliveries:
        logger.info(
            "Release update advisory is blocked until a global communications route exists",
            extra={
                "available_app_version": release.app_version,
                "available_chart_version": release.chart_version,
            },
        )
        return "blocked"

    for delivery in deliveries:
        if delivery.state in RETRYABLE_DELIVERY_STATES:
            await _deliver_route(notification, delivery)

    return await _finalize_notification(notification_id)


async def check_once() -> str:
    settings = get_settings()
    if not settings.release_update_notifications_enabled:
        return "disabled"

    async with _CHECK_LOCK:
        client = _client_from_settings()
        latest = await client.fetch_latest_release(
            include_prereleases=settings.release_update_notifications_include_prereleases
        )
        if latest is None:
            record_release_update_check("no_releases")
            return "no_releases"

        if not is_release_newer(
            latest,
            current_app_version=settings.app_version,
            current_chart_version=settings.chart_version,
        ):
            record_release_update_check("current")
            return "current"

        status = await process_release_notification(latest)
        record_release_update_check(status)
        return status


async def _checker_loop() -> None:
    while True:
        settings = get_settings()
        interval = max(int(settings.release_update_notifications_check_interval_seconds or 0), 60)
        try:
            await check_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            record_release_update_check("failed")
            logger.warning("Release update advisory check failed", extra={"error": str(exc)})
        await asyncio.sleep(interval)


async def start_release_update_notification_checker() -> None:
    global _CHECKER_TASK
    settings = get_settings()
    if not settings.release_update_notifications_enabled:
        return
    if _CHECKER_TASK is not None and not _CHECKER_TASK.done():
        return
    _CHECKER_TASK = asyncio.create_task(_checker_loop(), name="release-update-notifications")


async def stop_release_update_notification_checker() -> None:
    global _CHECKER_TASK
    if _CHECKER_TASK is None:
        return
    _CHECKER_TASK.cancel()
    try:
        await _CHECKER_TASK
    except asyncio.CancelledError:
        pass
    _CHECKER_TASK = None

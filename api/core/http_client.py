#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Shared httpx clients with retries and concurrency limits."""

import asyncio
import time
from typing import Any, Iterable

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.metrics import record_http_retry

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None


def _build_limits(settings) -> httpx.Limits:
    return httpx.Limits(
        max_connections=settings.httpx_max_connections,
        max_keepalive_connections=settings.httpx_max_keepalive,
    )


def _build_timeout(settings) -> httpx.Timeout:
    return httpx.Timeout(
        timeout=settings.httpx_timeout_seconds,
        connect=settings.httpx_connect_timeout_seconds,
        read=settings.httpx_read_timeout_seconds,
        write=settings.httpx_write_timeout_seconds,
    )


def get_async_http_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient instance."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=_build_timeout(settings),
            limits=_build_limits(settings),
            follow_redirects=True,
        )
    return _client


def get_sync_http_client() -> httpx.Client:
    """Return a shared sync Client instance."""
    global _sync_client
    if _sync_client is None:
        settings = get_settings()
        _sync_client = httpx.Client(
            timeout=_build_timeout(settings),
            limits=_build_limits(settings),
            follow_redirects=True,
        )
    return _sync_client


def _build_async_client(verify: bool | str | None = None) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=_build_timeout(settings),
        limits=_build_limits(settings),
        follow_redirects=True,
        verify=verify if verify is not None else True,
    )


def _build_sync_client(verify: bool | str | None = None) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=_build_timeout(settings),
        limits=_build_limits(settings),
        follow_redirects=True,
        verify=verify if verify is not None else True,
    )


async def close_async_http_client() -> None:
    """Close the shared AsyncClient if it exists."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def close_sync_http_client() -> None:
    """Close the shared sync Client if it exists."""
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None


def _endpoint_from_url(url: str) -> str:
    parsed = httpx.URL(url)
    return f"{parsed.host}{parsed.path}"


async def request_with_retry(
    method: str,
    url: str,
    *,
    retries: int | None = None,
    retry_backoff_seconds: float | None = None,
    retry_statuses: Iterable[int] | None = None,
    raise_for_status: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request with retry/backoff for transient failures."""
    settings = get_settings()
    max_retries = retries if retries is not None else settings.httpx_retries
    backoff = (
        retry_backoff_seconds
        if retry_backoff_seconds is not None
        else settings.httpx_retry_backoff_seconds
    )
    statuses = set(retry_statuses or settings.httpx_retry_statuses)

    verify = kwargs.pop("verify", None)
    client = get_async_http_client()
    close_client = False
    if verify is not None:
        client = _build_async_client(verify=verify)
        close_client = True
    endpoint = _endpoint_from_url(url)
    attempt = 0

    try:
        while True:
            attempt += 1
            try:
                response = await client.request(method, url, **kwargs)
                if raise_for_status:
                    response.raise_for_status()
                if response.status_code in statuses and attempt <= max_retries:
                    record_http_retry(method=method, endpoint=endpoint, reason="status")
                    await asyncio.sleep(backoff * (2 ** (attempt - 1)))
                    continue
                return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt > max_retries:
                    raise
                record_http_retry(method=method, endpoint=endpoint, reason="exception")
                logger.warning(
                    "HTTP request failed; retrying",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
    finally:
        if close_client:
            await client.aclose()


def request_with_retry_sync(
    method: str,
    url: str,
    *,
    retries: int | None = None,
    retry_backoff_seconds: float | None = None,
    retry_statuses: Iterable[int] | None = None,
    raise_for_status: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """Send a sync request with retry/backoff for transient failures."""
    settings = get_settings()
    max_retries = retries if retries is not None else settings.httpx_retries
    backoff = (
        retry_backoff_seconds
        if retry_backoff_seconds is not None
        else settings.httpx_retry_backoff_seconds
    )
    statuses = set(retry_statuses or settings.httpx_retry_statuses)

    verify = kwargs.pop("verify", None)
    client = get_sync_http_client()
    close_client = False
    if verify is not None:
        client = _build_sync_client(verify=verify)
        close_client = True
    endpoint = _endpoint_from_url(url)
    attempt = 0

    try:
        while True:
            attempt += 1
            try:
                response = client.request(method, url, **kwargs)
                if raise_for_status:
                    response.raise_for_status()
                if response.status_code in statuses and attempt <= max_retries:
                    record_http_retry(method=method, endpoint=endpoint, reason="status")
                    time_to_sleep = backoff * (2 ** (attempt - 1))
                    time.sleep(time_to_sleep)
                    continue
                return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt > max_retries:
                    raise
                record_http_retry(method=method, endpoint=endpoint, reason="exception")
                logger.warning(
                    "HTTP request failed; retrying",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "error": str(exc),
                    },
                )
                time_to_sleep = backoff * (2 ** (attempt - 1))
                time.sleep(time_to_sleep)
    finally:
        if close_client:
            client.close()

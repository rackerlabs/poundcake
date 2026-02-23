"""Neutral HTTP retry helpers without service-specific dependencies."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Any

import httpx


async def async_request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = 2,
    retry_backoff_seconds: float = 0.5,
    retry_statuses: Iterable[int] = (429, 500, 502, 503, 504),
    timeout: float | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send an async request with exponential backoff retries."""
    attempt = 0
    statuses = set(retry_statuses)
    timeout_obj = httpx.Timeout(timeout) if timeout is not None else None
    while True:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=timeout_obj, follow_redirects=True) as client:
                response = await client.request(method, url, **kwargs)
            if response.status_code in statuses and attempt <= retries:
                await asyncio.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            return response
        except (httpx.RequestError, httpx.TimeoutException):
            if attempt > retries:
                raise
            await asyncio.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))


def sync_request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = 2,
    retry_backoff_seconds: float = 0.5,
    retry_statuses: Iterable[int] = (429, 500, 502, 503, 504),
    timeout: float | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send a sync request with exponential backoff retries."""
    attempt = 0
    statuses = set(retry_statuses)
    timeout_obj = httpx.Timeout(timeout) if timeout is not None else None
    while True:
        attempt += 1
        try:
            with httpx.Client(timeout=timeout_obj, follow_redirects=True) as client:
                response = client.request(method, url, **kwargs)
            if response.status_code in statuses and attempt <= retries:
                time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            return response
        except (httpx.RequestError, httpx.TimeoutException):
            if attempt > retries:
                raise
            time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))

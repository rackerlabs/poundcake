#!/usr/bin/env python3
"""Prometheus metrics for Bakery."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

BAKERY_OPERATIONS_TOTAL = Counter(
    "bakery_operations_total",
    "Total number of Bakery operations by action/status",
    ["action", "status"],
)

BAKERY_OPERATION_LATENCY_SECONDS = Histogram(
    "bakery_operation_latency_seconds",
    "Latency for Bakery operation execution",
    ["action"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

BAKERY_RETRIES_TOTAL = Counter(
    "bakery_retries_total",
    "Total operation retries in Bakery worker",
    ["action"],
)

BAKERY_DEAD_LETTER_TOTAL = Counter(
    "bakery_dead_letter_total",
    "Total Bakery operations moved to dead letter",
    ["action"],
)


def render_metrics() -> tuple[bytes, str]:
    """Return serialized Prometheus metrics payload and content-type."""
    return generate_latest(), CONTENT_TYPE_LATEST

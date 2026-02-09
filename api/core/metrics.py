#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus metrics definitions for PoundCake."""

from prometheus_client import Counter, Histogram, Gauge, Info

# Application info
APP_INFO = Info("poundcake", "PoundCake application information")

# Alert metrics
ALERTS_RECEIVED = Counter(
    "poundcake_alerts_received_total", "Total number of alerts received", ["alertname", "severity"]
)

ALERTS_PROCESSED = Counter(
    "poundcake_alerts_processed_total", "Total number of alerts processed", ["alertname", "status"]
)

ALERTS_PROCESSING_DURATION = Histogram(
    "poundcake_alert_processing_duration_seconds",
    "Time spent processing alerts",
    ["alertname"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# Remediation metrics
REMEDIATIONS_EXECUTED = Counter(
    "poundcake_remediations_executed_total",
    "Total number of remediation actions executed",
    ["action", "status"],
)

REMEDIATION_DURATION = Histogram(
    "poundcake_remediation_duration_seconds",
    "Time spent executing remediation actions",
    ["action"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

# Task queue metrics
ACTIVE_TASKS = Gauge("poundcake_active_tasks", "Number of currently processing tasks")

QUEUED_TASKS = Gauge("poundcake_queued_tasks", "Number of tasks waiting in queue")

# StackStorm metrics
ST2_EXECUTIONS = Counter(
    "poundcake_st2_executions_total", "Total StackStorm action executions", ["action_ref", "status"]
)

ST2_EXECUTION_DURATION = Histogram(
    "poundcake_st2_execution_duration_seconds",
    "StackStorm action execution duration",
    ["action_ref"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
)

# API metrics
HTTP_REQUESTS = Counter(
    "poundcake_http_requests_total", "Total HTTP requests", ["method", "endpoint", "status_code"]
)

HTTP_REQUEST_DURATION = Histogram(
    "poundcake_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# HTTP retry metrics
HTTP_RETRIES = Counter(
    "poundcake_http_retries_total",
    "Total HTTP request retries",
    ["method", "endpoint", "reason"],
)

# Database metrics
DB_CONNECTIONS = Gauge("poundcake_db_connections", "Number of active database connections")

DB_QUERY_DURATION = Histogram(
    "poundcake_db_query_duration_seconds",
    "Database query duration",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# Mapping metrics
MAPPINGS_TOTAL = Gauge("poundcake_mappings_total", "Total number of configured mappings")

MAPPINGS_MATCHED = Counter(
    "poundcake_mappings_matched_total",
    "Total number of alerts matched to mappings",
    ["mapping_name"],
)


def init_app_info(app_name: str, version: str) -> None:
    """Initialize application info metric.

    Args:
        app_name: Application name
        version: Application version
    """
    APP_INFO.info(
        {
            "app_name": app_name,
            "version": version,
        }
    )


def record_alert_received(alertname: str, severity: str) -> None:
    """Record an alert received.

    Args:
        alertname: Name of the alert
        severity: Severity level
    """
    ALERTS_RECEIVED.labels(alertname=alertname, severity=severity or "unknown").inc()


def record_alert_processed(alertname: str, status: str) -> None:
    """Record an alert processed.

    Args:
        alertname: Name of the alert
        status: Processing status (completed, failed, etc.)
    """
    ALERTS_PROCESSED.labels(alertname=alertname, status=status).inc()


def record_remediation(action: str, status: str, duration: float | None = None) -> None:
    """Record a remediation execution.

    Args:
        action: Action reference
        status: Execution status
        duration: Execution duration in seconds
    """
    REMEDIATIONS_EXECUTED.labels(action=action, status=status).inc()
    if duration is not None:
        REMEDIATION_DURATION.labels(action=action).observe(duration)


def record_st2_execution(action_ref: str, status: str, duration: float | None = None) -> None:
    """Record a StackStorm execution.

    Args:
        action_ref: Action reference (pack.action)
        status: Execution status
        duration: Execution duration in seconds
    """
    ST2_EXECUTIONS.labels(action_ref=action_ref, status=status).inc()
    if duration is not None:
        ST2_EXECUTION_DURATION.labels(action_ref=action_ref).observe(duration)


def record_http_request(method: str, endpoint: str, status_code: int, duration: float) -> None:
    """Record an HTTP request.

    Args:
        method: HTTP method
        endpoint: Request endpoint
        status_code: Response status code
        duration: Request duration in seconds
    """
    HTTP_REQUESTS.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
    HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


def record_http_retry(method: str, endpoint: str, reason: str) -> None:
    """Record an HTTP retry attempt.

    Args:
        method: HTTP method
        endpoint: Request endpoint
        reason: Retry reason (status/exception)
    """
    HTTP_RETRIES.labels(method=method, endpoint=endpoint, reason=reason).inc()


def update_active_tasks(count: int) -> None:
    """Update the active tasks gauge.

    Args:
        count: Current number of active tasks
    """
    ACTIVE_TASKS.set(count)


def update_queued_tasks(count: int) -> None:
    """Update the queued tasks gauge.

    Args:
        count: Current number of queued tasks
    """
    QUEUED_TASKS.set(count)


def update_mappings_total(count: int) -> None:
    """Update the total mappings gauge.

    Args:
        count: Total number of mappings
    """
    MAPPINGS_TOTAL.set(count)


def record_mapping_match(mapping_name: str) -> None:
    """Record a mapping match.

    Args:
        mapping_name: Name of the matched mapping
    """
    MAPPINGS_MATCHED.labels(mapping_name=mapping_name).inc()

#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus API client and rule management service.

Ported from poundcake/src/poundcake/prometheus.py.
Note: CRD manager and Git integration can be added as separate modules.
"""

from api.core.logging import get_logger
from typing import Any
import time

from api.core.config import get_settings
from api.core.http_client import request_with_retry
from api.core.httpx_utils import silence_httpx

logger = get_logger(__name__)
SYSTEM_REQ_ID = "SYSTEM-PROM"


class PrometheusClient:
    """Client for interacting with Prometheus API."""

    def __init__(self) -> None:
        """Initialize the Prometheus client."""
        settings = get_settings()
        self.base_url = settings.prometheus_url.rstrip("/")
        self.verify_ssl = settings.prometheus_verify_ssl
        self.retries = settings.external_http_retries

    async def _request(self, method: str, path_or_url: str, **kwargs):
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        return await request_with_retry(
            method, url, verify=self.verify_ssl, retries=self.retries, **kwargs
        )

    async def get_rules(self) -> list[dict[str, Any]]:
        """Fetch all alert rules from Prometheus.

        Returns:
            List of alert rule groups with their rules
        """
        try:
            start_time = time.time()
            response = await self._request(
                "GET",
                "/api/v1/rules",
                params={"type": "alert"},
                timeout=30,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    groups = data.get("data", {}).get("groups", [])
                    return self._flatten_rules(groups)
                else:
                    logger.error(
                        "Prometheus API returned error",
                        extra={
                            "req_id": SYSTEM_REQ_ID,
                            "method": "GET",
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                            "error": data.get("error"),
                        },
                    )
                    return []
            else:
                logger.error(
                    "Failed to fetch Prometheus rules",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return []
        except Exception as e:
            logger.error(
                "Error fetching Prometheus rules",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "error": str(e),
                },
            )
            return []

    def _flatten_rules(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten rule groups into a list of individual rules."""
        rules = []
        for group in groups:
            group_name = group.get("name", "")
            group_file = group.get("file", "")
            group_interval = group.get("interval", 0)

            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    rules.append(
                        {
                            "group": group_name,
                            "file": group_file,
                            "interval": group_interval,
                            "name": rule.get("name", ""),
                            "query": rule.get("query", ""),
                            "duration": rule.get("duration", ""),
                            "labels": rule.get("labels", {}),
                            "annotations": rule.get("annotations", {}),
                            "state": rule.get("state", ""),
                            "health": rule.get("health", ""),
                            "type": rule.get("type", ""),
                            "alerts": rule.get("alerts", []),
                        }
                    )
        return rules

    async def get_rule_groups(self) -> list[dict[str, Any]]:
        """Get all rule groups with their full structure."""
        try:
            start_time = time.time()
            response = await self._request("GET", "/api/v1/rules", timeout=30)
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return data.get("data", {}).get("groups", [])
                else:
                    logger.error(
                        "Prometheus API returned error",
                        extra={
                            "req_id": SYSTEM_REQ_ID,
                            "method": "GET",
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                            "error": data.get("error"),
                        },
                    )
                    return []
            else:
                logger.error(
                    "Failed to fetch Prometheus rule groups",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return []
        except Exception as e:
            logger.error(
                "Error fetching Prometheus rule groups",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "error": str(e),
                },
            )
            return []

    async def health_check(self) -> dict[str, Any]:
        """Check if Prometheus is reachable."""
        try:
            with silence_httpx():
                start_time = time.time()
                response = await self._request("GET", "/-/healthy", timeout=10, retries=0)
                latency_ms = int((time.time() - start_time) * 1000)
                return {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "url": self.base_url,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "url": self.base_url,
                "error": str(e),
            }

    async def reload_config(self) -> dict[str, Any]:
        """Reload Prometheus configuration.

        Note: Requires Prometheus to be started with --web.enable-lifecycle flag.
        """
        settings = get_settings()

        if not settings.prometheus_reload_enabled:
            return {
                "status": "disabled",
                "message": "Prometheus reload is not enabled in settings",
            }

        try:
            reload_url = (
                settings.prometheus_reload_url
                if settings.prometheus_reload_url
                else f"{self.base_url}/-/reload"
            )

            start_time = time.time()
            response = await self._request("POST", reload_url, timeout=30)
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                logger.info(
                    "Prometheus configuration reloaded successfully",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "POST",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return {
                    "status": "success",
                    "message": "Prometheus configuration reloaded",
                }
            else:
                logger.error(
                    "Failed to reload Prometheus",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "POST",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                        "error": response.text,
                    },
                )
                return {
                    "status": "error",
                    "message": f"Failed to reload: {response.status_code}",
                    "detail": response.text,
                }
        except Exception as e:
            logger.error(
                "Error reloading Prometheus",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "POST",
                    "error": str(e),
                },
            )
            return {
                "status": "error",
                "message": str(e),
            }

    async def get_metric_names(self) -> list[str]:
        """Fetch all available metric names from Prometheus."""
        try:
            start_time = time.time()
            response = await self._request(
                "GET",
                "/api/v1/label/__name__/values",
                timeout=30,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return data.get("data", [])
                else:
                    logger.error(
                        "Prometheus API returned error",
                        extra={
                            "req_id": SYSTEM_REQ_ID,
                            "method": "GET",
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                            "error": data.get("error"),
                        },
                    )
                    return []
            else:
                logger.error(
                    "Failed to fetch metric names",
                    extra={
                        "req_id": SYSTEM_REQ_ID,
                        "method": "GET",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    },
                )
                return []
        except Exception as e:
            logger.error(
                "Error fetching metric names",
                extra={"req_id": SYSTEM_REQ_ID, "method": "GET", "error": str(e)},
            )
            return []

    async def get_label_names(self, metric: str | None = None) -> list[str]:
        """Fetch all available label names from Prometheus.

        Args:
            metric: Optional metric name to get labels for a specific metric
        """
        try:
            if metric:
                start_time = time.time()
                response = await self._request(
                    "GET",
                    "/api/v1/label/__name__/values",
                    params={"match[]": metric},
                    timeout=30,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        labels = data.get("data", [])
                        return [label for label in labels if label != "__name__"]
            else:
                start_time = time.time()
                response = await self._request("GET", "/api/v1/labels", timeout=30)
                latency_ms = int((time.time() - start_time) * 1000)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        labels = data.get("data", [])
                        return [label for label in labels if label != "__name__"]

            logger.error(
                "Failed to fetch label names",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Error fetching label names",
                extra={"req_id": SYSTEM_REQ_ID, "method": "GET", "error": str(e)},
            )
            return []

    async def get_label_values(
        self,
        label_name: str,
        metric: str | None = None,
    ) -> list[str]:
        """Fetch all available values for a specific label.

        Args:
            label_name: The label name to get values for
            metric: Optional metric name to filter values
        """
        try:
            if metric:
                start_time = time.time()
                response = await self._request(
                    "GET",
                    "/api/v1/series",
                    params={"match[]": metric},
                    timeout=30,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        values = set()
                        for series in data.get("data", []):
                            if label_name in series:
                                values.add(series[label_name])
                        return sorted(list(values))
            else:
                start_time = time.time()
                response = await self._request(
                    "GET",
                    f"/api/v1/label/{label_name}/values",
                    timeout=30,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data", [])

            logger.error(
                "Failed to fetch label values",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "label_name": label_name,
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Error fetching label values",
                extra={
                    "req_id": SYSTEM_REQ_ID,
                    "method": "GET",
                    "label_name": label_name,
                    "error": str(e),
                },
            )
            return []


# Global client instance
_prometheus_client: PrometheusClient | None = None


def get_prometheus_client() -> PrometheusClient:
    """Get the global Prometheus client instance."""
    global _prometheus_client
    if _prometheus_client is None:
        _prometheus_client = PrometheusClient()
    return _prometheus_client

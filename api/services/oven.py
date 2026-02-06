#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven service - scheduled crawler for processing alerts."""

import asyncio
import os
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from api.core.logging import get_logger
from api.core.config import get_settings
from api.core.http_client import request_with_retry

logger = get_logger(__name__)
settings = get_settings()


class OvenService:
    """Oven service for scheduled alert processing via API calls only."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize oven service with PoundCake API base URL."""
        # Ensure we don't have trailing slashes
        self.base_url = (base_url or os.getenv("POUNDCAKE_API_URL", "http://api:8000")).rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"

    async def crawl_and_process_alerts(self) -> Dict[str, Any]:
        """Crawl alerts table for NEW alerts and trigger processing."""
        try:
            logger.info("Oven crawler: Starting alert scan")

            # Step 1: GET alerts with processing_status = 'new'
            alerts = await self._get_new_alerts()

            if not alerts:
                logger.info("Oven crawler: No new alerts found")
                return {"status": "no_alerts", "alerts_processed": 0}

            logger.info(f"Oven crawler: Found {len(alerts)} new alerts")

            processed_count = 0
            errors = []

            semaphore = asyncio.Semaphore(settings.max_concurrent_remediations)

            async def _process(alert: Dict[str, Any]) -> None:
                nonlocal processed_count
                async with semaphore:
                    try:
                        result = await self._process_single_alert(alert)
                        if result.get("success"):
                            processed_count += 1
                    except Exception as e:
                        logger.error(f"Oven crawler: Error processing alert {alert.get('id')}: {e}")
                        errors.append({"alert_id": alert.get("id"), "error": str(e)})

            await asyncio.gather(*[_process(alert) for alert in alerts])

            return {
                "status": "complete",
                "alerts_found": len(alerts),
                "alerts_processed": processed_count,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Oven crawler: Fatal error: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _get_new_alerts(self) -> List[Dict[str, Any]]:
        """GET alerts with processing_status = 'new' from API."""
        try:
            start_time = time.time()
            response = await request_with_retry(
                "GET",
                f"{self.api_base}/alerts",
                params={"processing_status": "new", "limit": 100},
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()
                # Handle both direct list or wrapped object response
                return data if isinstance(data, list) else data.get("alerts", [])

            logger.error(
                "Failed to fetch new alerts",
                extra={
                    "method": "GET",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                },
            )
            return []
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Error fetching new alerts",
                extra={"method": "GET", "latency_ms": latency_ms, "error": str(e)},
            )
            return []

    async def _get_recipe_by_group_name(
        self, group_name: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """GET recipe from API based on group_name."""
        if not group_name:
            return None

        try:
            # Fixed: Added v1 and pluralized correctly to match main.py
            start_time = time.time()
            response = await request_with_retry(
                "GET",
                f"{self.api_base}/recipes",
                params={"name": group_name},
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                recipes = response.json()
                return recipes[0] if recipes and isinstance(recipes, list) else None
            logger.error(
                "Failed to fetch recipe",
                extra={
                    "method": "GET",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "group_name": group_name,
                },
            )
            return None
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Error fetching recipe",
                extra={
                    "method": "GET",
                    "latency_ms": latency_ms,
                    "group_name": group_name,
                    "error": str(e),
                },
            )
            return None

    async def _trigger_task_execution(
        self, alert_id: int, recipe_id: int, task_id: str, req_id: str
    ) -> Dict[str, Any]:
        """POST to /api/v1/alerts/process to trigger task execution."""
        try:
            start_time = time.time()
            response = await request_with_retry(
                "POST",
                f"{self.api_base}/alerts/process",
                json={
                    "alert_id": alert_id,
                    "recipe_id": recipe_id,
                    "task_id": task_id,
                },
                headers={"X-Request-ID": req_id},  # Pass req_id in headers for tracing
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code in [200, 201, 202]:
                return response.json()

            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return {"success": False, "error": str(e), "latency_ms": latency_ms}

    async def _process_single_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Orchestrate the processing of a single alert."""
        alert_id = alert.get("id")
        req_id = alert.get("req_id", "unknown")
        group_name = alert.get("group_name")

        recipe = await self._get_recipe_by_group_name(group_name)
        if not recipe:
            return {"success": False, "reason": "no_recipe"}

        ingredients = recipe.get("ingredients", [])
        semaphore = asyncio.Semaphore(settings.max_concurrent_remediations)

        async def _trigger(ing: Dict[str, Any]) -> None:
            async with semaphore:
                await self._trigger_task_execution(
                    alert_id, recipe.get("id"), ing.get("task_id"), req_id
                )

        await asyncio.gather(*[_trigger(ing) for ing in ingredients])

        return {"success": True}

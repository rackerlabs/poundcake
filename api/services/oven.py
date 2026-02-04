#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven service - scheduled crawler for processing alerts."""

import os
import time
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from api.core.logging import get_logger

logger = get_logger(__name__)


class OvenService:
    """Oven service for scheduled alert processing via API calls only."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize oven service with PoundCake API base URL."""
        # Ensure we don't have trailing slashes
        self.base_url = (base_url or os.getenv("POUNDCAKE_API_URL", "http://api:8000")).rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"

    def crawl_and_process_alerts(self) -> Dict[str, Any]:
        """Crawl alerts table for NEW alerts and trigger processing."""
        try:
            logger.info("Oven crawler: Starting alert scan")

            # Step 1: GET alerts with processing_status = 'new'
            alerts = self._get_new_alerts()

            if not alerts:
                logger.info("Oven crawler: No new alerts found")
                return {"status": "no_alerts", "alerts_processed": 0}

            logger.info(f"Oven crawler: Found {len(alerts)} new alerts")

            processed_count = 0
            errors = []

            for alert in alerts:
                try:
                    result = self._process_single_alert(alert)
                    if result.get("success"):
                        processed_count += 1
                except Exception as e:
                    logger.error(f"Oven crawler: Error processing alert {alert.get('id')}: {e}")
                    errors.append({"alert_id": alert.get("id"), "error": str(e)})

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

    def _get_new_alerts(self) -> List[Dict[str, Any]]:
        """GET alerts with processing_status = 'new' from API."""
        try:
            response = requests.get(
                f"{self.api_base}/alerts",
                params={"processing_status": "new", "limit": 100},
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                # Handle both direct list or wrapped object response
                return data if isinstance(data, list) else data.get("alerts", [])

            logger.error(f"Failed to fetch new alerts: {response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching new alerts: {e}")
            return []

    def _get_recipe_by_group_name(self, group_name: Optional[str]) -> Optional[Dict[str, Any]]:
        """GET recipe from API based on group_name."""
        if not group_name:
            return None

        try:
            # Fixed: Added v1 and pluralized correctly to match main.py
            response = requests.get(
                f"{self.api_base}/recipes",
                params={"name": group_name},
                timeout=10,
            )

            if response.status_code == 200:
                recipes = response.json()
                return recipes[0] if recipes and isinstance(recipes, list) else None
            return None
        except Exception as e:
            logger.error(f"Error fetching recipe for {group_name}: {e}")
            return None

    def _trigger_task_execution(
        self, alert_id: int, recipe_id: int, task_id: str, req_id: str
    ) -> Dict[str, Any]:
        """POST to /api/v1/alerts/process to trigger task execution."""
        try:
            response = requests.post(
                f"{self.api_base}/alerts/process",
                json={
                    "alert_id": alert_id,
                    "recipe_id": recipe_id,
                    "task_id": task_id,
                },
                headers={"X-Request-ID": req_id},  # Pass req_id in headers for tracing
                timeout=60,
            )

            if response.status_code in [200, 201, 202]:
                return response.json()

            return {"success": False, "error": response.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _process_single_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Orchestrate the processing of a single alert."""
        alert_id = alert.get("id")
        req_id = alert.get("req_id", "unknown")
        group_name = alert.get("group_name")

        recipe = self._get_recipe_by_group_name(group_name)
        if not recipe:
            return {"success": False, "reason": "no_recipe"}

        ingredients = recipe.get("ingredients", [])
        for ing in ingredients:
            self._trigger_task_execution(alert_id, recipe.get("id"), ing.get("task_id"), req_id)

        return {"success": True}

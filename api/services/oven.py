#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Oven service - scheduled crawler for processing alerts.

This service runs as a scheduled background task that:
1. Crawls the alerts table looking for processing_status = 'NEW'
2. For each NEW alert, queries recipes by group_name
3. Parses recipe.task_list (comma-separated UUIDs)
4. Creates one oven entry per task in task_list
5. POSTs to /api/v1/alerts/process to trigger task execution

The oven service ONLY talks to PoundCake API endpoints - it does NOT
access the database directly. All database operations and StackStorm
integration happen through the API layer.
"""

import os
import time
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime

from api.core.logging import get_logger

logger = get_logger(__name__)


class OvenService:
    """Oven service for scheduled alert processing via API calls only."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize oven service with PoundCake API base URL.

        Args:
            base_url: PoundCake API base URL (e.g., 'http://localhost:8000')
                     Defaults to POUNDCAKE_API_URL env var or localhost
        """
        self.base_url = base_url or os.getenv("POUNDCAKE_API_URL", "http://localhost:8000")
        self.api_base = f"{self.base_url}/api/v1"

    def crawl_and_process_alerts(self) -> Dict[str, Any]:
        """Crawl alerts table for NEW alerts and trigger processing.

        This is the main entry point for the scheduled crawler.

        Returns:
            Dictionary with processing statistics
        """
        try:
            logger.info("Oven crawler: Starting alert scan")

            # Step 1: GET alerts with processing_status = 'new'
            alerts = self._get_new_alerts()

            if not alerts:
                logger.info("Oven crawler: No new alerts found")
                return {"status": "no_alerts", "alerts_processed": 0}

            logger.info(f"Oven crawler: Found {len(alerts)} new alerts")

            # Step 2: Process each alert
            processed_count = 0
            errors = []

            for alert in alerts:
                try:
                    result = self._process_single_alert(alert)
                    if result.get("success"):
                        processed_count += 1
                except Exception as e:
                    logger.error(
                        f"Oven crawler: Error processing alert {alert.get('id')}: {e}",
                        exc_info=True,
                    )
                    errors.append({"alert_id": alert.get("id"), "error": str(e)})

            logger.info(f"Oven crawler: Processed {processed_count}/{len(alerts)} alerts")

            return {
                "status": "complete",
                "alerts_found": len(alerts),
                "alerts_processed": processed_count,
                "errors": errors,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Oven crawler: Fatal error: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def _get_new_alerts(self) -> List[Dict[str, Any]]:
        """GET alerts with processing_status = 'new' from API.

        Returns:
            List of alert dictionaries
        """
        try:
            response = requests.get(
                f"{self.api_base}/alerts",
                params={"processing_status": "new", "limit": 100},
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    f"Failed to fetch new alerts: {response.status_code} - {response.text}"
                )
                return []

        except Exception as e:
            logger.error(f"Error fetching new alerts: {e}", exc_info=True)
            return []

    def _process_single_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single alert by creating ovens and triggering execution.

        Steps:
        1. Get recipe based on alert.group_name
        2. Parse recipe.task_list
        3. For each task, POST to /api/v1/alerts/process

        Args:
            alert: Alert dictionary from API

        Returns:
            Result dictionary with success status
        """
        alert_id = alert.get("id")
        alert_req_id = alert.get("req_id")
        group_name = alert.get("group_name")

        logger.info(
            f"Oven: Processing alert {alert_id} with group_name={group_name}",
            extra={"req_id": alert_req_id},
        )

        # Step 1: Get recipe for this alert
        recipe = self._get_recipe_by_group_name(group_name)

        if not recipe:
            logger.warning(
                f"Oven: No recipe found for group_name={group_name}",
                extra={"req_id": alert_req_id, "alert_id": alert_id},
            )
            return {"success": False, "reason": "no_recipe"}

        recipe_id = recipe.get("id")
        task_list_str = recipe.get("task_list")

        logger.info(
            f"Oven: Matched recipe '{recipe.get('name')}' (id={recipe_id})",
            extra={"req_id": alert_req_id},
        )

        # Step 2: Parse task_list (comma-separated UUIDs)
        tasks = self._parse_task_list(task_list_str)

        if not tasks:
            logger.warning(
                f"Oven: Recipe {recipe_id} has empty task_list",
                extra={"req_id": alert_req_id},
            )
            return {"success": False, "reason": "empty_task_list"}

        logger.info(
            f"Oven: Recipe has {len(tasks)} tasks to process",
            extra={"req_id": alert_req_id},
        )

        # Step 3: POST to /alerts/process for each task
        # This will create oven entries and trigger execution
        for task_id in tasks:
            try:
                self._trigger_task_execution(alert_id, recipe_id, task_id, alert_req_id)
            except Exception as e:
                logger.error(
                    f"Oven: Error triggering task {task_id}: {e}",
                    exc_info=True,
                    extra={"req_id": alert_req_id},
                )

        return {"success": True, "tasks_triggered": len(tasks)}

    def _get_recipe_by_group_name(self, group_name: Optional[str]) -> Optional[Dict[str, Any]]:
        """GET recipe from API based on group_name.

        Args:
            group_name: Group name from alert

        Returns:
            Recipe dictionary or None
        """
        if not group_name:
            return None

        try:
            # GET /api/recipes/?name={group_name}
            response = requests.get(
                f"{self.base_url}/api/recipes/",
                params={"name": group_name},
                timeout=10,
            )

            if response.status_code == 200:
                recipes = response.json()
                if recipes:
                    return recipes[0]  # Return first match

            return None

        except Exception as e:
            logger.error(f"Error fetching recipe for group_name={group_name}: {e}", exc_info=True)
            return None

    def _parse_task_list(self, task_list_str: Optional[str]) -> List[str]:
        """Parse comma-separated task_list into list of task UUIDs.

        Args:
            task_list_str: Comma-separated string like "uuid1,uuid2,uuid3"

        Returns:
            List of task UUID strings
        """
        if not task_list_str:
            return []

        # Split by comma and strip whitespace
        tasks = [task.strip() for task in task_list_str.split(",") if task.strip()]
        return tasks

    def _trigger_task_execution(
        self, alert_id: int, recipe_id: int, task_id: str, req_id: str
    ) -> Dict[str, Any]:
        """POST to /api/v1/alerts/process to trigger single task execution.

        This endpoint will:
        - Create oven entry with status='new' and task_id
        - Update alert.processing_status = 'processing'
        - Call StackStorm API
        - Store execution_id in oven.action_id
        - Update oven.status = 'processing'

        Args:
            alert_id: Alert ID
            recipe_id: Recipe ID
            task_id: Task UUID from recipe.task_list
            req_id: Request ID for tracking

        Returns:
            Response dictionary from API
        """
        try:
            logger.info(
                f"Oven: Triggering task {task_id} for alert {alert_id}",
                extra={"req_id": req_id},
            )

            # POST /api/v1/alerts/process with specific alert and task
            response = requests.post(
                f"{self.api_base}/alerts/process",
                json={
                    "alert_id": alert_id,
                    "recipe_id": recipe_id,
                    "task_id": task_id,
                },
                timeout=60,
            )

            if response.status_code in [200, 202]:
                result = response.json()
                logger.info(
                    f"Oven: Task {task_id} triggered successfully",
                    extra={"req_id": req_id},
                )
                return result
            else:
                logger.error(
                    f"Oven: Failed to trigger task: {response.status_code} - {response.text}",
                    extra={"req_id": req_id},
                )
                return {"success": False, "error": response.text}

        except Exception as e:
            logger.error(
                f"Oven: Error triggering task: {e}", exc_info=True, extra={"req_id": req_id}
            )
            return {"success": False, "error": str(e)}


def run_oven_crawler_once() -> Dict[str, Any]:
    """Run oven crawler once (for testing or manual execution).

    Returns:
        Processing statistics
    """
    oven = OvenService()
    return oven.crawl_and_process_alerts()


def run_oven_crawler_loop(interval_seconds: int = 60):
    """Run oven crawler in a loop with specified interval.

    Args:
        interval_seconds: Seconds to wait between crawls (default: 60)
    """
    oven = OvenService()
    logger.info(f"Oven crawler: Starting loop with {interval_seconds}s interval")

    while True:
        try:
            result = oven.crawl_and_process_alerts()
            logger.info(f"Oven crawler: Cycle complete - {result}")
        except Exception as e:
            logger.error(f"Oven crawler: Unexpected error: {e}", exc_info=True)

        time.sleep(interval_seconds)

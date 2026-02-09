#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""StackStorm API client and action management service."""

import asyncio
import time
import os
import re
from pathlib import Path
from typing import Any

import yaml

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.httpx_utils import silence_httpx
from api.core.statuses import ST2_TERMINAL_STATUSES
from api.models.models import Recipe

logger = get_logger(__name__)


class StackStormError(Exception):
    """Exception raised for StackStorm API errors."""

    pass


class StackStormClient:
    """Client for interacting with StackStorm API."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the StackStorm client.

        Args:
            api_key: Optional API key to use. If not provided, reads from settings on each request.
        """
        settings = get_settings()
        self.base_url = settings.stackstorm_url.rstrip("/")
        self.verify_ssl = settings.stackstorm_verify_ssl
        # Don't cache API key - _get_headers() will read it dynamically
        self._auth_token: str | None = settings.stackstorm_auth_token or None

    def _get_headers(self) -> dict[str, str]:
        """Get headers with current API key.

        Re-reads the API key on each call to support runtime key generation.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }

        # Re-read API key from settings (which checks the file each time)
        settings = get_settings()
        api_key = settings.get_stackstorm_api_key()

        if api_key:
            headers["St2-Api-Key"] = api_key
        elif self._auth_token:
            headers["X-Auth-Token"] = self._auth_token

        return headers

    async def execute_action(
        self,
        action_ref: str,
        req_id: str,
        parameters: dict[str, Any] | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Execute a StackStorm action.

        Args:
            action_ref: The action reference (pack.action_name)
            parameters: Parameters to pass to the action
            timeout: Request timeout in seconds
            req_id: Original request id from dishes.req_id

        Returns:
            The execution result from StackStorm
        """
        payload = {
            "action": action_ref,
            "parameters": parameters or {},
        }

        headers = self._get_headers()

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(timeout),
        ) as client:
            try:
                start_time = time.time()
                logger.info(
                    "Executing StackStorm action",
                    extra={"req_id": req_id, "action_ref": action_ref, "method": "POST"},
                )

                response = await client.post(
                    f"{self.base_url}/v1/executions",
                    headers=headers,
                    json=payload,
                )
                latency_ms = int((time.time() - start_time) * 1000)

                if response.status_code == 201:
                    result: dict[str, Any] = response.json()
                    logger.info(
                        "Action execution started successfully",
                        extra={
                            "req_id": req_id,
                            "action_ref": action_ref,
                            "method": "POST",
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                            "execution_id": result.get("id"),
                            "status": result.get("status"),
                        },
                    )
                    return result
                else:
                    error_msg = f"StackStorm API error: {response.status_code} - {response.text}"
                    logger.error(
                        "StackStorm API error",
                        extra={
                            "req_id": req_id,
                            "action_ref": action_ref,
                            "method": "POST",
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                            "error": response.text,
                        },
                    )
                    raise StackStormError(error_msg)

            except httpx.TimeoutException as e:
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    "StackStorm request timed out",
                    extra={
                        "req_id": req_id,
                        "action_ref": action_ref,
                        "method": "POST",
                        "timeout": timeout,
                        "latency_ms": latency_ms,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                raise StackStormError(f"StackStorm request timed out after {timeout}s") from e

            except httpx.RequestError as e:
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    "StackStorm request failed",
                    extra={
                        "req_id": req_id,
                        "action_ref": action_ref,
                        "method": "POST",
                        "latency_ms": latency_ms,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                raise StackStormError(f"StackStorm request failed: {e}") from e

    async def get_execution(self, execution_id: str) -> dict[str, Any]:
        """Get the status of a StackStorm execution.

        Args:
            execution_id: The execution ID to check

        Returns:
            The execution details
        """
        headers = self._get_headers()

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self.base_url}/v1/executions/{execution_id}",
                headers=headers,
            )

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result
            else:
                raise StackStormError(
                    f"Failed to get execution {execution_id}: {response.status_code}"
                )

    async def get_execution_tasks(self, execution_id: str) -> list[dict[str, Any]]:
        """Get task results for a StackStorm execution (Orquesta)."""
        headers = self._get_headers()

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self.base_url}/v1/executions/{execution_id}/tasks",
                headers=headers,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            raise StackStormError(
                f"Failed to get execution tasks {execution_id}: {response.status_code}"
            )

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a StackStorm execution."""
        headers = self._get_headers()

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.put(
                f"{self.base_url}/v1/executions/{execution_id}",
                headers=headers,
                json={"status": "canceled"},
            )

            if response.status_code in (200, 202, 204):
                return True
            raise StackStormError(
                f"Failed to cancel execution {execution_id}: {response.status_code}"
            )

    async def delete_execution(self, execution_id: str) -> bool:
        """Delete a StackStorm execution record."""
        headers = self._get_headers()

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.delete(
                f"{self.base_url}/v1/executions/{execution_id}",
                headers=headers,
            )

            if response.status_code in (200, 202, 204):
                return True
            raise StackStormError(
                f"Failed to delete execution {execution_id}: {response.status_code}"
            )

    async def wait_for_execution(
        self,
        execution_id: str,
        timeout: int = 300,
        poll_interval: int = 2,
    ) -> dict[str, Any]:
        """Wait for a StackStorm execution to complete.

        Args:
            execution_id: The execution ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            The final execution result
        """
        elapsed = 0
        while elapsed < timeout:
            result = await self.get_execution(execution_id)
            status = result.get("status", "")

            if status in ST2_TERMINAL_STATUSES:
                return result

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise StackStormError(f"Execution {execution_id} timed out after {timeout}s")

    async def health_check(self, req_id: str | None = None) -> bool:
        """Check if StackStorm API is accessible."""
        headers = self._get_headers()
        if req_id:
            headers["X-Request-ID"] = req_id

        with silence_httpx():
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(10),
            ) as client:
                try:
                    start_time = time.time()
                    response = await client.get(
                        f"{self.base_url}/v1/actions",
                        headers=headers,
                        params={"limit": 1},
                    )
                    return response.status_code == 200
                except Exception as e:
                    latency_ms = int((time.time() - start_time) * 1000)
                    logger.warning(
                        "StackStorm health check failed",
                        extra=(
                            {
                                "req_id": req_id,
                                "method": "GET",
                                "latency_ms": latency_ms,
                                "error": str(e),
                            }
                            if req_id
                            else {"method": "GET", "error": str(e)}
                        ),
                    )
                    return False


class StackStormActionManager:
    """Manager for StackStorm actions, packs, and executions."""

    def __init__(self, client: StackStormClient | None = None) -> None:
        """Initialize with a StackStorm client."""
        self._client = client or StackStormClient()

    async def list_actions(
        self,
        pack: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List available StackStorm actions.

        Args:
            pack: Filter by pack name
            limit: Maximum number of actions to return

        Returns:
            List of action definitions
        """
        params: dict[str, Any] = {"limit": limit}
        if pack:
            params["pack"] = pack

        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/v1/actions",
                headers=headers,
                params=params,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []

    async def list_non_orquesta_actions(self, limit: int = 1000) -> list[dict[str, Any]]:
        """List non-Orquesta StackStorm actions (runner_type != orquesta)."""
        actions = await self._list_all_actions(limit=limit)
        return [a for a in actions if a.get("runner_type") != "orquesta"]

    async def list_orquesta_actions(self, limit: int = 1000) -> list[dict[str, Any]]:
        """List Orquesta StackStorm actions (runner_type == orquesta)."""
        actions = await self._list_all_actions(limit=limit)
        return [a for a in actions if a.get("runner_type") == "orquesta"]

    async def _list_all_actions(self, limit: int = 1000) -> list[dict[str, Any]]:
        """List all StackStorm actions with pagination."""
        headers = self._client._get_headers()
        actions: list[dict[str, Any]] = []
        offset = 0

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            while True:
                response = await client.get(
                    f"{self._client.base_url}/v1/actions",
                    headers=headers,
                    params={"limit": limit, "offset": offset},
                )
                if response.status_code != 200:
                    break
                batch: list[dict[str, Any]] = response.json()
                if not batch:
                    break
                actions.extend(batch)
                offset += limit

        return actions

    async def get_action(self, action_ref: str) -> dict[str, Any] | None:
        """Get details of a specific action.

        Args:
            action_ref: Action reference (pack.action)

        Returns:
            Action definition or None
        """
        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/v1/actions/{action_ref}",
                headers=headers,
            )

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result
            return None

    async def list_packs(self) -> list[dict[str, Any]]:
        """List available StackStorm packs.

        Returns:
            List of pack definitions
        """
        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/v1/packs",
                headers=headers,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []

    async def get_execution_history(
        self,
        limit: int = 50,
        action: str | None = None,
        parent: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get StackStorm execution history.

        Args:
            limit: Maximum number of executions
            action: Filter by action reference

        Returns:
            List of executions
        """
        params: dict[str, Any] = {"limit": limit, "sort_desc": "start_timestamp"}
        if action:
            params["action"] = action
        if parent:
            params["parent"] = parent

        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/v1/executions",
                headers=headers,
                params=params,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []

    async def update_action(
        self,
        action_ref: str,
        action_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update a StackStorm action definition.

        Args:
            action_ref: Action reference (pack.action)
            action_data: Updated action definition

        Returns:
            Updated action definition or None if failed
        """
        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.put(
                f"{self._client.base_url}/v1/actions/{action_ref}",
                headers=headers,
                json=action_data,
            )

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                logger.info(
                    "StackStorm action updated successfully",
                    extra={"action_ref": action_ref},
                )
                return result
            else:
                logger.error(
                    "Failed to update StackStorm action",
                    extra={
                        "action_ref": action_ref,
                        "status_code": response.status_code,
                        "error": response.text,
                    },
                )
                return None

    async def create_action(
        self,
        action_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Create a new StackStorm action.

        Args:
            action_data: Action definition

        Returns:
            Created action definition or None if failed
        """
        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.post(
                f"{self._client.base_url}/v1/actions",
                headers=headers,
                json=action_data,
            )

            if response.status_code == 201:
                result: dict[str, Any] = response.json()
                logger.info(
                    "StackStorm action created successfully",
                    extra={"action_ref": result.get("ref")},
                )
                return result
            else:
                logger.error(
                    "Failed to create StackStorm action",
                    extra={"status_code": response.status_code, "error": response.text},
                )
                return None

    async def delete_action(self, action_ref: str) -> bool:
        """Delete a StackStorm action.

        Args:
            action_ref: Action reference (pack.action)

        Returns:
            True if successful
        """
        headers = self._client._get_headers()

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.delete(
                f"{self._client.base_url}/v1/actions/{action_ref}",
                headers=headers,
            )

            if response.status_code == 204:
                logger.info(
                    "StackStorm action deleted successfully",
                    extra={"action_ref": action_ref},
                )
                return True
            else:
                logger.error(
                    "Failed to delete StackStorm action",
                    extra={"action_ref": action_ref, "status_code": response.status_code},
                )
        return False



def generate_orquesta_yaml(recipe_object: Recipe | dict[str, Any]) -> str:
    """
    Converts a Recipe (model or dict) and its RecipeIngredients into a StackStorm
    Orquesta-compatible YAML string.
    """

    if isinstance(recipe_object, dict):
        name = recipe_object.get("name")
        description = recipe_object.get("description")
        recipe_ingredients = recipe_object.get("recipe_ingredients", [])
        sorted_steps = sorted(recipe_ingredients, key=lambda x: x.get("step_order", 1))
    else:
        name = recipe_object.name
        description = recipe_object.description
        sorted_steps = sorted(recipe_object.recipe_ingredients, key=lambda x: x.step_order)

    workflow = {
        "version": "1.0",
        "description": description or f"Workflow for {name}",
        "tasks": {},
    }
    last_task_name: str | None = None

    for i, ri in enumerate(sorted_steps):
        if isinstance(recipe_object, dict):
            ingredient = ri.get("ingredient") or {}
            step_order = ri.get("step_order")
            task_name_raw = ingredient.get("task_name", "task")
            task_id = ingredient.get("task_id")
            action_parameters = ingredient.get("action_parameters") or {}
            retry_count = ingredient.get("retry_count") or 0
            retry_delay = ingredient.get("retry_delay")
            is_blocking = ingredient.get("is_blocking", True)
        else:
            ingredient = ri.ingredient
            if ingredient is None:
                continue
            step_order = ri.step_order
            task_name_raw = ingredient.task_name
            task_id = ingredient.task_id
            action_parameters = ingredient.action_parameters or {}
            retry_count = ingredient.retry_count
            retry_delay = ingredient.retry_delay
            is_blocking = ingredient.is_blocking

        task_name = f"step_{step_order}_{task_name_raw.replace('.', '_')}"
        last_task_name = task_name

        task_def: dict[str, Any] = {
            "action": task_id,
            "input": action_parameters,
        }

        if retry_count > 0:
            task_def["retry"] = {
                "count": retry_count,
                "delay": retry_delay,
            }

        if i < len(sorted_steps) - 1:
            next_step = sorted_steps[i + 1]
            if isinstance(recipe_object, dict):
                next_ing = next_step.get("ingredient") or {}
                next_task_name_raw = next_ing.get("task_name", "task")
                next_step_order = next_step.get("step_order")
            else:
                next_ing = next_step.ingredient
                if next_ing is None:
                    next_task_name_raw = None
                    next_step_order = None
                else:
                    next_task_name_raw = next_ing.task_name
                    next_step_order = next_step.step_order

            if next_task_name_raw is not None and next_step_order is not None:
                next_task_name = (
                    f"step_{next_step_order}_{next_task_name_raw.replace('.', '_')}"
                )
                if is_blocking:
                    task_def["next"] = [{"when": "<% succeeded() %>", "do": next_task_name}]
                else:
                    task_def["next"] = [{"do": next_task_name}]

        workflow["tasks"][task_name] = task_def

    # Capture the final task result as workflow output for easier consumption.
    if last_task_name:
        workflow["output"] = {"result": f"<% task({last_task_name}).result %>"}

    return yaml.dump(workflow, sort_keys=False)


async def register_workflow_to_st2(
    st2_url: str,
    api_key: str,
    recipe: Recipe | dict[str, Any],
) -> str:
    """
    Registers an Orquesta workflow in StackStorm by writing the workflow YAML
    into a shared pack directory and creating the action via the API.
    Returns the created action ref.
    """
    headers = {"St2-Api-Key": api_key, "Content-Type": "application/json"}

    workflow_payload = (
        recipe.get("workflow_payload") if isinstance(recipe, dict) else recipe.workflow_payload
    )
    yaml_payload = (
        yaml.dump(workflow_payload, sort_keys=False)
        if isinstance(workflow_payload, dict)
        else generate_orquesta_yaml(recipe)
    )

    recipe_name = recipe.get("name") if isinstance(recipe, dict) else recipe.name
    # Safe filename for workflow
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", recipe_name or "workflow")

    pack_name = os.getenv("POUNDCAKE_ST2_PACK", "poundcake")
    pack_root = Path(os.getenv("POUNDCAKE_ST2_PACK_ROOT", "/app/stackstorm-packs")) / pack_name
    # StackStorm expects orquesta workflows under pack/actions/workflows
    actions_dir = pack_root / "actions"
    workflows_dir = actions_dir / "workflows"

    pack_root.mkdir(parents=True, exist_ok=True)
    pack_yaml = pack_root / "pack.yaml"
    if not pack_yaml.exists():
        pack_yaml.write_text(
            "name: {}\nversion: \"0.1.0\"\ndescription: \"PoundCake generated pack\"\n"
            "author: \"PoundCake\"\n".format(pack_name)
        )

    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = workflows_dir / f"{safe_name}.yaml"
    workflow_file.write_text(yaml_payload)

    st2_action_data = {
        "name": safe_name,
        "pack": pack_name,
        "runner_type": "orquesta",
        "entry_point": f"workflows/{safe_name}.yaml",
        "enabled": True,
        "parameters": (
            recipe.get("workflow_parameters")
            if isinstance(recipe, dict)
            else (recipe.workflow_parameters or {})
        ),
        "description": recipe.get("description")
        if isinstance(recipe, dict)
        else recipe.description,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{st2_url}/v1/actions",
            json=st2_action_data,
            headers=headers,
        )

        if response.status_code in [200, 201]:
            data = response.json()
            return data.get("ref")
        if response.status_code == 409:
            # Action already exists; return expected ref
            return f"{pack_name}.{safe_name}"
        raise StackStormError(f"Failed to register ST2 action: {response.text}")


# Global instances
_client: StackStormClient | None = None
_action_manager: StackStormActionManager | None = None


def get_stackstorm_client() -> StackStormClient:
    """Get the global StackStorm client."""
    global _client
    if _client is None:
        _client = StackStormClient()
    return _client


def get_action_manager() -> StackStormActionManager:
    """Get the global StackStorm action manager."""
    global _action_manager
    if _action_manager is None:
        _action_manager = StackStormActionManager(get_stackstorm_client())
    return _action_manager

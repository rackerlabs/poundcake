#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""StackStorm API client and action management service."""

import asyncio
import hashlib
import io
import time
import os
import re
import tarfile
from typing import Any

import yaml

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.httpx_utils import silence_httpx
from api.core.http_client import request_with_retry
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
        self.retries = settings.external_http_retries
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

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        retries = kwargs.pop("retries", self.retries)
        return await request_with_retry(
            method,
            f"{self.base_url}{path}",
            verify=self.verify_ssl,
            retries=retries,
            **kwargs,
        )

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

        start_time = time.time()
        try:
            logger.info(
                "Executing StackStorm action",
                extra={"req_id": req_id, "action_ref": action_ref, "method": "POST"},
            )

            response = await self._request(
                "POST",
                "/v1/executions",
                headers=headers,
                json=payload,
                timeout=timeout,
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

        response = await self._request(
            "GET",
            f"/v1/executions/{execution_id}",
            headers=headers,
            timeout=30,
        )

        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result
        raise StackStormError(f"Failed to get execution {execution_id}: {response.status_code}")

    async def get_execution_tasks(self, execution_id: str) -> list[dict[str, Any]]:
        """Get task results for a StackStorm execution (Orquesta)."""
        headers = self._get_headers()

        response = await self._request(
            "GET",
            f"/v1/executions/{execution_id}/tasks",
            headers=headers,
            timeout=30,
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

        response = await self._request(
            "PUT",
            f"/v1/executions/{execution_id}",
            headers=headers,
            json={"status": "canceled"},
            timeout=30,
        )

        if response.status_code in (200, 202, 204):
            return True
        raise StackStormError(f"Failed to cancel execution {execution_id}: {response.status_code}")

    async def delete_execution(self, execution_id: str) -> bool:
        """Delete a StackStorm execution record."""
        headers = self._get_headers()

        response = await self._request(
            "DELETE",
            f"/v1/executions/{execution_id}",
            headers=headers,
            timeout=30,
        )

        if response.status_code in (200, 202, 204):
            return True
        raise StackStormError(f"Failed to delete execution {execution_id}: {response.status_code}")

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

        start_time = time.time()
        with silence_httpx():
            try:
                response = await self._request(
                    "GET",
                    "/v1/actions",
                    headers=headers,
                    params={"limit": 1},
                    timeout=10,
                    retries=0,
                )
                # 200 => authenticated and healthy
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
        self._retries = self._client.retries

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        retries = kwargs.pop("retries", self._retries)
        return await request_with_retry(
            method,
            f"{self._client.base_url}{path}",
            verify=self._client.verify_ssl,
            retries=retries,
            **kwargs,
        )

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

        response = await self._request(
            "GET",
            "/v1/actions",
            headers=headers,
            params=params,
            timeout=30,
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

        while True:
            response = await self._request(
                "GET",
                "/v1/actions",
                headers=headers,
                params={"limit": limit, "offset": offset},
                timeout=30,
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

        response = await self._request(
            "GET",
            f"/v1/actions/{action_ref}",
            headers=headers,
            timeout=30,
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

        response = await self._request(
            "GET",
            "/v1/packs",
            headers=headers,
            timeout=30,
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

        response = await self._request(
            "GET",
            "/v1/executions",
            headers=headers,
            params=params,
            timeout=30,
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

        response = await self._request(
            "PUT",
            f"/v1/actions/{action_ref}",
            headers=headers,
            json=action_data,
            timeout=30,
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

        response = await self._request(
            "POST",
            "/v1/actions",
            headers=headers,
            json=action_data,
            timeout=30,
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

        response = await self._request(
            "DELETE",
            f"/v1/actions/{action_ref}",
            headers=headers,
            timeout=30,
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
    task_defs: list[dict[str, Any]] = []

    for i, ri in enumerate(sorted_steps):
        if isinstance(recipe_object, dict):
            run_phase = (ri.get("run_phase") or "both").lower()
        else:
            run_phase = (ri.run_phase or "both").lower()
        if run_phase not in ("firing", "both"):
            continue

        if isinstance(recipe_object, dict):
            ingredient = ri.get("ingredient") or {}
            step_order = ri.get("step_order")
            depth = ri.get("depth") or 0
            task_name_raw = ingredient.get("task_key_template", "task")
            task_id = ingredient.get("execution_target")
            input_parameters = ri.get("execution_parameters_override") or {}
            retry_count = ingredient.get("retry_count") or 0
            retry_delay = ingredient.get("retry_delay")
            is_blocking = ingredient.get("is_blocking", True)
            on_failure = str(ingredient.get("on_failure") or "stop").lower()
        else:
            ingredient = ri.ingredient
            if ingredient is None:
                continue
            step_order = ri.step_order
            depth = ri.depth
            task_name_raw = ingredient.task_key_template
            task_id = ingredient.execution_target
            input_parameters = ri.execution_parameters_override or {}
            retry_count = ingredient.retry_count
            retry_delay = ingredient.retry_delay
            is_blocking = ingredient.is_blocking
            on_failure = str(ingredient.on_failure or "stop").lower()

        task_name = f"step_{step_order}_{task_name_raw.replace('.', '_')}"
        last_task_name = task_name

        task_def: dict[str, Any] = {
            "action": task_id,
            "input": input_parameters,
        }

        if retry_count > 0:
            task_def["retry"] = {
                "count": retry_count,
                "delay": retry_delay,
            }

        task_defs.append(
            {
                "name": task_name,
                "def": task_def,
                "depth": depth,
                "step_order": step_order,
                "is_blocking": is_blocking,
                "on_failure": on_failure,
            }
        )

    # Build stages either by explicit depth or by is_blocking sequencing when depth is absent.
    tasks_by_depth: dict[int, list[dict[str, Any]]] = {}
    for t in task_defs:
        tasks_by_depth.setdefault(t["depth"], []).append(t)
    for depth in tasks_by_depth:
        tasks_by_depth[depth] = sorted(tasks_by_depth[depth], key=lambda x: x["step_order"])

    def _add_transition(from_task: dict[str, Any], target_names: list[str], when_expr: str) -> None:
        if not target_names:
            return
        transition = {
            "when": when_expr,
            "do": target_names if len(target_names) > 1 else target_names[0],
        }
        next_items = from_task["def"].setdefault("next", [])
        if transition not in next_items:
            next_items.append(transition)

    def _connect_stages(prev_stage: list[dict[str, Any]], next_stage: list[dict[str, Any]]) -> None:
        if not prev_stage or not next_stage:
            return

        next_names = [t["name"] for t in next_stage]

        # Multiple upstream tasks converging into one downstream task must fan-in.
        if len(prev_stage) > 1 and len(next_stage) == 1:
            next_stage[0]["def"]["join"] = "all"

        # Also support many-to-many stage transitions by joining each downstream task.
        if len(prev_stage) > 1 and len(next_stage) > 1:
            for next_task in next_stage:
                next_task["def"]["join"] = "all"

        for prev_task in prev_stage:
            _add_transition(prev_task, next_names, "<% succeeded() %>")
            if prev_task.get("on_failure") == "continue":
                _add_transition(prev_task, next_names, "<% failed() %>")

    stages: list[list[dict[str, Any]]] = []
    has_explicit_depth = any(t["depth"] > 0 for t in task_defs)

    if has_explicit_depth:
        for depth in sorted(tasks_by_depth):
            stages.append(tasks_by_depth[depth])
    else:
        ordered_tasks = sorted(task_defs, key=lambda x: x["step_order"])
        for task in ordered_tasks:
            if task["is_blocking"]:
                stages.append([task])
            else:
                if stages and not stages[-1][0]["is_blocking"]:
                    stages[-1].append(task)
                else:
                    stages.append([task])

    for i in range(1, len(stages)):
        _connect_stages(stages[i - 1], stages[i])

    # Emit tasks in a stable order.
    for t in sorted(task_defs, key=lambda x: (x["depth"], x["step_order"])):
        workflow["tasks"][t["name"]] = t["def"]
        last_task_name = t["name"]

    # Capture the final task result as workflow output for easier consumption.
    if last_task_name:
        # Orquesta expects workflow output to be a list of assignments.
        workflow["output"] = [{"result": f"<% task({last_task_name}).result %>"}]

    return yaml.safe_dump(workflow, sort_keys=False, default_flow_style=False, width=1000, indent=2)


def _safe_workflow_name(name: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "workflow")


def _normalize_execution_parameters(recipe: Recipe | dict[str, Any]) -> dict[str, Any]:
    """Return StackStorm action parameters as a JSON object."""
    if not isinstance(recipe, dict):
        return {}

    if "execution_parameters" not in recipe:
        return {}

    execution_parameters = recipe.get("execution_parameters")
    if execution_parameters is None:
        return {}

    if not isinstance(execution_parameters, dict):
        raise ValueError("execution_parameters must be an object when provided")

    return execution_parameters


def build_stackstorm_pack_files(
    recipes: list[Recipe | dict[str, Any]],
    pack_name: str | None = None,
) -> dict[str, bytes]:
    """Build an in-memory StackStorm pack file tree from recipe workflow sources."""
    resolved_pack_name = pack_name or os.getenv("POUNDCAKE_ST2_PACK", "poundcake")

    files: dict[str, bytes] = {
        "pack.yaml": (
            f"name: {resolved_pack_name}\n"
            'version: "0.1.0"\n'
            'description: "PoundCake generated pack"\n'
            'author: "PoundCake"\n'
        ).encode("utf-8")
    }

    for recipe in recipes:
        recipe_name = recipe.get("name") if isinstance(recipe, dict) else recipe.name

        try:
            yaml_payload = generate_orquesta_yaml(recipe)
        except Exception as exc:
            logger.warning(
                "Skipping recipe while building StackStorm pack files",
                extra={"recipe_name": recipe_name, "error": str(exc)},
            )
            continue

        safe_name = _safe_workflow_name(recipe_name)
        files[f"actions/workflows/{safe_name}.yaml"] = yaml_payload.encode("utf-8")

    return files


def build_stackstorm_pack_artifact(
    recipes: list[Recipe | dict[str, Any]],
    pack_name: str | None = None,
) -> tuple[bytes, str]:
    """Create a deterministic tar.gz payload and etag for StackStorm pack sync."""
    files = build_stackstorm_pack_files(recipes=recipes, pack_name=pack_name)

    digest = hashlib.sha256()
    for path in sorted(files):
        payload = files[path]
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(payload)
        digest.update(b"\x00")
    etag = f'"{digest.hexdigest()}"'

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(files):
            payload = files[path]
            info = tarfile.TarInfo(name=path)
            info.size = len(payload)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))

    return buf.getvalue(), etag


async def register_workflow_to_st2(
    st2_url: str,
    api_key: str,
    recipe: Recipe | dict[str, Any],
) -> str:
    """
    Registers an Orquesta workflow action in StackStorm.
    Workflow files are distributed to StackStorm pods through pack-sync sidecars.
    Returns the created action ref.
    """
    headers = {"St2-Api-Key": api_key, "Content-Type": "application/json"}

    recipe_name = recipe.get("name") if isinstance(recipe, dict) else recipe.name
    safe_name = _safe_workflow_name(recipe_name)

    pack_name = os.getenv("POUNDCAKE_ST2_PACK", "poundcake")

    st2_action_data = {
        "name": safe_name,
        "pack": pack_name,
        "runner_type": "orquesta",
        "entry_point": f"workflows/{safe_name}.yaml",
        "enabled": True,
        "parameters": _normalize_execution_parameters(recipe),
        "description": (
            recipe.get("description") if isinstance(recipe, dict) else recipe.description
        ),
    }

    settings = get_settings()
    retries = max(1, settings.stackstorm_pack_sync_register_retries)
    delay_seconds = max(0.5, settings.stackstorm_pack_sync_register_delay_seconds)
    last_response: httpx.Response | None = None

    for attempt in range(1, retries + 1):
        response = await request_with_retry(
            "POST",
            f"{st2_url}/v1/actions",
            json=st2_action_data,
            headers=headers,
            timeout=30,
            retries=settings.external_http_retries,
        )
        last_response = response

        if response.status_code in [200, 201]:
            data = response.json()
            return data.get("ref")
        if response.status_code == 409:
            # Action already exists; return expected ref
            return f"{pack_name}.{safe_name}"

        # StackStorm may take a short period to see newly synced pack files.
        if "Content pack" in (response.text or "") and attempt < retries:
            await asyncio.sleep(delay_seconds)
            continue
        break

    if last_response is None:
        raise StackStormError("Failed to register ST2 action: no response from StackStorm API")

    if "Content pack" in (last_response.text or ""):
        raise StackStormError(
            "Failed to register ST2 action because StackStorm has not yet loaded the generated "
            f"workflow in pack '{pack_name}'. Ensure pack-sync sidecars can reach the PoundCake "
            f"pack endpoint. StackStorm response: {last_response.text}"
        )

    raise StackStormError(f"Failed to register ST2 action: {last_response.text}")


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

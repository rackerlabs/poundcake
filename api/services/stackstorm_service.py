#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""StackStorm API client and action management service."""

import asyncio
import time
from typing import Any

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.httpx_utils import silence_httpx
from api.core.http_client import request_with_retry

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
            req_id: Orignal request id from ovens.req_id

        Returns:
            The execution result from StackStorm
        """
        payload = {
            "action": action_ref,
            "parameters": parameters or {},
        }

        headers = self._get_headers()

        try:
            start_time = time.time()
            logger.info(
                "Executing StackStorm action",
                extra={"req_id": req_id, "action_ref": action_ref, "method": "POST"},
            )

            response = await request_with_retry(
                "POST",
                f"{self.base_url}/v1/executions",
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(timeout),
                verify=self.verify_ssl,
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

        response = await request_with_retry(
            "GET",
            f"{self.base_url}/v1/executions/{execution_id}",
            headers=headers,
            timeout=httpx.Timeout(30),
            verify=self.verify_ssl,
        )

        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result
        raise StackStormError(
            f"Failed to get execution {execution_id}: {response.status_code}"
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

            if status in ("succeeded", "failed", "timeout", "abandoned", "canceled"):
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
            try:
                start_time = time.time()
                response = await request_with_retry(
                    "GET",
                    f"{self.base_url}/v1/actions",
                    headers=headers,
                    params={"limit": 1},
                    timeout=httpx.Timeout(10),
                    verify=self.verify_ssl,
                )
                return response.status_code == 200
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    "StackStorm health check failed",
                    extra={
                        "req_id": req_id,
                        "method": "GET",
                        "latency_ms": latency_ms,
                        "error": str(e),
                    }
                    if req_id
                    else {"method": "GET", "error": str(e)},
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

        response = await request_with_retry(
            "GET",
            f"{self._client.base_url}/v1/actions",
            headers=headers,
            params=params,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
        )

        if response.status_code == 200:
            result: list[dict[str, Any]] = response.json()
            return result
        return []

    async def get_action(self, action_ref: str) -> dict[str, Any] | None:
        """Get details of a specific action.

        Args:
            action_ref: Action reference (pack.action)

        Returns:
            Action definition or None
        """
        headers = self._client._get_headers()

        response = await request_with_retry(
            "GET",
            f"{self._client.base_url}/v1/actions/{action_ref}",
            headers=headers,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
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

        response = await request_with_retry(
            "GET",
            f"{self._client.base_url}/v1/packs",
            headers=headers,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
        )

        if response.status_code == 200:
            result: list[dict[str, Any]] = response.json()
            return result
        return []

    async def get_execution_history(
        self,
        limit: int = 50,
        action: str | None = None,
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

        headers = self._client._get_headers()

        response = await request_with_retry(
            "GET",
            f"{self._client.base_url}/v1/executions",
            headers=headers,
            params=params,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
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

        response = await request_with_retry(
            "PUT",
            f"{self._client.base_url}/v1/actions/{action_ref}",
            headers=headers,
            json=action_data,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
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

        response = await request_with_retry(
            "POST",
            f"{self._client.base_url}/v1/actions",
            headers=headers,
            json=action_data,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
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

        response = await request_with_retry(
            "DELETE",
            f"{self._client.base_url}/v1/actions/{action_ref}",
            headers=headers,
            timeout=httpx.Timeout(30),
            verify=self._client.verify_ssl,
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

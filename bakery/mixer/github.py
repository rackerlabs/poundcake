#!/usr/bin/env python3
"""GitHub mixer for issue management."""

from typing import Dict, Any
import httpx

from bakery.config import settings
from bakery.mixer.base import BaseMixer


class GitHubMixer(BaseMixer):
    """Mixer for GitHub issue management."""

    def __init__(self) -> None:
        """Initialize GitHub mixer."""
        super().__init__()
        self.token = settings.github_token
        self.timeout = settings.mixer_timeout_sec
        self.base_url = "https://api.github.com"

    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process GitHub issue request.

        Args:
            action: Action to perform (create, update, close, comment)
            data: Request data

        Returns:
            Response dictionary with success status and issue details
        """
        if not self.token:
            return {
                "success": False,
                "error": "GitHub token not configured",
            }

        try:
            if action == "create":
                return await self._create_issue(data)
            elif action == "update":
                return await self._update_issue(data)
            elif action == "close":
                return await self._close_issue(data)
            elif action == "comment":
                return await self._add_comment(data)
            elif action == "search":
                return await self._search_issues(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for GitHub API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _create_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new GitHub issue."""
        owner = data.get("owner")
        repo = data.get("repo")

        if not owner or not repo:
            return {
                "success": False,
                "error": "owner and repo required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/issues",
                headers=self._get_headers(),
                json={
                    "title": data.get("title", ""),
                    "body": data.get("description", ""),
                    "labels": data.get("labels", []),
                    "assignees": data.get("assignees", []),
                },
            )
            response.raise_for_status()
            result = response.json()

            return {
                "success": True,
                "ticket_id": str(result["number"]),
                "data": result,
            }

    async def _update_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing GitHub issue."""
        owner = data.get("owner")
        repo = data.get("repo")
        ticket_id = data.get("ticket_id")

        if not owner or not repo or not ticket_id:
            return {
                "success": False,
                "error": "owner, repo, and ticket_id required for update",
            }

        update_data: Dict[str, Any] = {}
        if "title" in data:
            update_data["title"] = data["title"]
        if "description" in data:
            update_data["body"] = data["description"]
        if "labels" in data:
            update_data["labels"] = data["labels"]
        if "assignees" in data:
            update_data["assignees"] = data["assignees"]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/repos/{owner}/{repo}/issues/{ticket_id}",
                headers=self._get_headers(),
                json=update_data,
            )
            response.raise_for_status()

            return {
                "success": True,
                "ticket_id": ticket_id,
            }

    async def _close_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Close a GitHub issue."""
        owner = data.get("owner")
        repo = data.get("repo")
        ticket_id = data.get("ticket_id")

        if not owner or not repo or not ticket_id:
            return {
                "success": False,
                "error": "owner, repo, and ticket_id required for close",
            }

        close_notes = data.get("close_notes")
        if close_notes:
            comment_result = await self._add_comment(
                {
                    "owner": owner,
                    "repo": repo,
                    "ticket_id": ticket_id,
                    "comment": close_notes,
                }
            )
            if not comment_result.get("success"):
                return comment_result

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/repos/{owner}/{repo}/issues/{ticket_id}",
                headers=self._get_headers(),
                json={"state": "closed"},
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _add_comment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a comment to a GitHub issue."""
        owner = data.get("owner")
        repo = data.get("repo")
        ticket_id = data.get("ticket_id")
        comment = data.get("comment")

        if not owner or not repo or not ticket_id or not comment:
            return {
                "success": False,
                "error": "owner, repo, ticket_id, and comment required",
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/issues/{ticket_id}/comments",
                headers=self._get_headers(),
                json={"body": comment},
            )
            response.raise_for_status()

            return {"success": True, "ticket_id": ticket_id}

    async def _search_issues(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search GitHub issues.

        Supports two modes:
        - Full-text search: provide "query" to search via GitHub search API
        - List/filter: provide "owner" and "repo" with optional filters

        Args:
            data: Search parameters:
                - owner: Repository owner (required)
                - repo: Repository name (required)
                - query: Full-text search string (optional, uses search API)
                - state: Filter by state - open, closed, all (default "open")
                - labels: Filter by labels (list of strings, optional)
                - limit: Max results per page (default 20)
                - page: Page number for pagination (default 1)
        """
        owner = data.get("owner")
        repo = data.get("repo")

        if not owner or not repo:
            return {
                "success": False,
                "error": "owner and repo required for search",
            }

        query = data.get("query")
        limit = data.get("limit", 20)
        page = data.get("page", 1)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if query:
                # Use GitHub search API
                search_query = f"{query}+repo:{owner}/{repo}"
                if data.get("state"):
                    search_query += f"+state:{data['state']}"

                response = await client.get(
                    f"{self.base_url}/search/issues",
                    headers=self._get_headers(),
                    params={
                        "q": search_query,
                        "per_page": limit,
                        "page": page,
                    },
                )
                response.raise_for_status()
                result = response.json()

                return {
                    "success": True,
                    "data": {
                        "results": result.get("items", []),
                        "count": len(result.get("items", [])),
                        "total": result.get("total_count", 0),
                    },
                }
            else:
                # Use list issues API with filters
                params: Dict[str, Any] = {
                    "state": data.get("state", "open"),
                    "per_page": limit,
                    "page": page,
                }
                labels = data.get("labels")
                if labels:
                    params["labels"] = ",".join(labels)

                response = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/issues",
                    headers=self._get_headers(),
                    params=params,
                )
                response.raise_for_status()
                results = response.json()

                return {
                    "success": True,
                    "data": {
                        "results": results,
                        "count": len(results),
                        "total": len(results),
                    },
                }

    async def validate_credentials(self) -> bool:
        """Validate GitHub credentials."""
        if not self.token:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/user",
                    headers=self._get_headers(),
                )
                return response.status_code == 200
        except Exception:
            return False

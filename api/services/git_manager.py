#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Git repository manager for PoundCake Git-backed configuration workflows."""

import os
import shutil
import tempfile
import importlib
from pathlib import Path
from typing import Any

from api.core.http_client import request_with_retry

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger(__name__)


class GitManager:
    """Manages Git repository operations for PoundCake configuration sync."""

    def __init__(self) -> None:
        """Initialize the Git manager."""
        self.settings = get_settings()
        self.retries = self.settings.external_http_retries
        self.work_dir = Path(tempfile.gettempdir()) / "poundcake-git"
        self.repo_path: Path | None = None

    async def clone_or_pull(self) -> bool:
        """
        Clone the repository or pull latest changes.

        Returns:
            True if successful
        """
        if not self.settings.git_enabled or not self.settings.git_repo_url:
            logger.warning("Git not enabled or repo URL not configured")
            return False

        git = self._load_git_module()
        if git is None:
            return False

        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            repo_name = self.settings.git_repo_url.split("/")[-1].replace(".git", "")
            self.repo_path = self.work_dir / repo_name
            repo_url = self._credentialed_repo_url()

            if self.repo_path.exists():
                repo = git.Repo(self.repo_path)
                origin = repo.remotes.origin
                if repo_url != self.settings.git_repo_url:
                    origin.set_url(repo_url)
                origin.pull(self.settings.git_branch, env=self._get_git_env())
                logger.info("Pulled latest changes", extra={"repo": str(self.repo_path)})
            else:
                env = self._get_git_env()
                git.Repo.clone_from(
                    repo_url,
                    self.repo_path,
                    branch=self.settings.git_branch,
                    env=env,
                )
                logger.info("Cloned repository", extra={"repo": str(self.repo_path)})

            return True
        except Exception as e:
            logger.error("Failed to clone/pull repository", extra={"error": str(e)})
            return False

    def _get_git_env(self) -> dict[str, str]:
        """
        Get environment variables for Git operations.

        Returns:
            Environment variables with Git credentials
        """
        env = os.environ.copy()

        if self.settings.git_token:
            if "github.com" in self.settings.git_repo_url:
                env["GIT_ASKPASS"] = "echo"
                env["GIT_USERNAME"] = "oauth2"
                env["GIT_PASSWORD"] = self.settings.git_token
            elif "gitlab.com" in self.settings.git_repo_url:
                env["GIT_ASKPASS"] = "echo"
                env["GIT_USERNAME"] = "oauth2"
                env["GIT_PASSWORD"] = self.settings.git_token

        if self.settings.git_ssh_key_path:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.settings.git_ssh_key_path} -o StrictHostKeyChecking=no"
            )

        return env

    def _credentialed_repo_url(self) -> str:
        """Embed HTTPS token credentials into the repo URL when supported."""
        repo_url = str(self.settings.git_repo_url or "").strip()
        token = str(self.settings.git_token or "").strip()
        if not token or not repo_url.startswith("https://"):
            return repo_url
        if "github.com" in repo_url:
            return repo_url.replace("https://", f"https://x-access-token:{token}@")
        if "gitlab.com" in repo_url:
            return repo_url.replace("https://", f"https://oauth2:{token}@")
        return repo_url

    def _load_git_module(self) -> Any | None:
        """Load GitPython and surface the real import failure when unavailable."""
        try:
            return importlib.import_module("git")
        except ImportError as exc:
            logger.error("Git repository support unavailable", extra={"error": str(exc)})
            return None

    async def commit_and_push_deletion(
        self,
        file_path: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        """
        Delete a file and push changes to a new branch.

        Args:
            file_path: Relative path to file in repo
            commit_message: Commit message

        Returns:
            Tuple of (success, branch_name)
        """
        return await self.commit_and_push_files(
            {file_path: None},
            commit_message,
            branch_prefix="poundcake-rule-update",
        )

    async def commit_and_push_changes(
        self,
        file_path: str,
        content: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        """
        Commit and push changes to a new branch.

        Args:
            file_path: Relative path to file in repo
            content: New file content
            commit_message: Commit message

        Returns:
            Tuple of (success, branch_name)
        """
        return await self.commit_and_push_files(
            {file_path: content},
            commit_message,
            branch_prefix="poundcake-rule-update",
        )

    async def commit_and_push_files(
        self,
        changes: dict[str, str | None],
        commit_message: str,
        *,
        branch_prefix: str = "poundcake-sync",
    ) -> tuple[bool, str]:
        """Commit and push a set of file writes and deletions."""
        if not changes:
            logger.warning("No Git changes were provided")
            return False, ""

        if not self.repo_path:
            if not await self.clone_or_pull():
                return False, ""

        git = self._load_git_module()
        if git is None:
            return False, ""

        try:
            assert self.repo_path is not None
            repo = git.Repo(self.repo_path)

            branch_name = f"{branch_prefix}-{os.urandom(4).hex()}"
            current_ref = str(repo.head.reference)
            repo.create_head(branch_name)
            repo.git.checkout(branch_name)

            added_paths: list[str] = []
            removed_paths: list[str] = []

            for file_path, content in sorted(changes.items()):
                full_path = self.repo_path / file_path
                if content is None:
                    if full_path.exists():
                        full_path.unlink()
                    if file_path in repo.git.ls_files(file_path).splitlines():
                        removed_paths.append(file_path)
                    continue

                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                added_paths.append(file_path)

            if added_paths:
                repo.index.add(added_paths)
            if removed_paths:
                repo.index.remove(removed_paths)

            repo.config_writer().set_value("user", "name", self.settings.git_user_name).release()
            repo.config_writer().set_value("user", "email", self.settings.git_user_email).release()

            if not repo.is_dirty(untracked_files=True):
                repo.git.checkout(current_ref)
                repo.delete_head(branch_name, force=True)
                logger.info("Skipping Git push because there are no material changes")
                return True, ""

            repo.index.commit(commit_message)

            env = self._get_git_env()
            credentialed_url = self._credentialed_repo_url()
            if credentialed_url != self.settings.git_repo_url:
                repo.remotes.origin.set_url(credentialed_url)

            repo.git.push("--set-upstream", "origin", branch_name, env=env)
            repo.git.checkout(current_ref)

            logger.info(
                "Committed and pushed repository changes",
                extra={
                    "branch": branch_name,
                    "changed_files": sorted(changes),
                },
            )
            return True, branch_name
        except Exception as e:
            logger.error("Failed to commit and push repository changes", extra={"error": str(e)})
            return False, ""

    async def create_pull_request(
        self,
        branch_name: str,
        title: str,
        description: str,
    ) -> dict[str, Any] | None:
        """
        Create a pull request.

        Args:
            branch_name: Source branch name
            title: PR title
            description: PR description

        Returns:
            PR information or None if failed
        """
        if self.settings.git_provider == "none":
            logger.info("Git provider is 'none', skipping PR creation")
            return None

        if self.settings.git_provider == "github":
            return await self._create_github_pr(branch_name, title, description)
        elif self.settings.git_provider == "gitlab":
            return await self._create_gitlab_pr(branch_name, title, description)
        elif self.settings.git_provider == "gitea":
            return await self._create_gitea_pr(branch_name, title, description)
        else:
            logger.warning("Unknown git provider", extra={"provider": self.settings.git_provider})
            return None

    async def _create_github_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a GitHub pull request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            repo_parts = repo_url.split("github.com/")[-1].split("/")
            owner, repo = repo_parts[0], repo_parts[1]

            api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"

            headers = {
                "Authorization": f"token {self.settings.git_token}",
                "Accept": "application/vnd.github.v3+json",
            }

            data = {
                "title": title,
                "body": description,
                "head": branch_name,
                "base": self.settings.git_branch,
            }

            response = await request_with_retry(
                "POST",
                api_url,
                headers=headers,
                json=data,
                timeout=30,
                retries=self.retries,
            )
            if response.status_code == 201:
                pr_data = response.json()
                logger.info(
                    "Created GitHub PR",
                    extra={
                        "pr_number": pr_data.get("number"),
                        "url": pr_data.get("html_url"),
                    },
                )
                return pr_data
            else:
                logger.error(
                    "Failed to create GitHub PR",
                    extra={
                        "status": response.status_code,
                        "response": response.text,
                    },
                )
                return None
        except Exception as e:
            logger.error("Error creating GitHub PR", extra={"error": str(e)})
            return None

    async def _create_gitlab_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a GitLab merge request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            repo_parts = repo_url.split("gitlab.com/")[-1]
            project_path = repo_parts.replace("/", "%2F")

            api_url = f"https://gitlab.com/api/v4/projects/{project_path}/merge_requests"

            headers = {
                "PRIVATE-TOKEN": self.settings.git_token,
            }

            data = {
                "source_branch": branch_name,
                "target_branch": self.settings.git_branch,
                "title": title,
                "description": description,
            }

            response = await request_with_retry(
                "POST",
                api_url,
                headers=headers,
                json=data,
                timeout=30,
                retries=self.retries,
            )
            if response.status_code == 201:
                mr_data = response.json()
                logger.info(
                    "Created GitLab MR",
                    extra={
                        "mr_iid": mr_data.get("iid"),
                        "url": mr_data.get("web_url"),
                    },
                )
                return mr_data
            else:
                logger.error(
                    "Failed to create GitLab MR",
                    extra={
                        "status": response.status_code,
                        "response": response.text,
                    },
                )
                return None
        except Exception as e:
            logger.error("Error creating GitLab MR", extra={"error": str(e)})
            return None

    async def _create_gitea_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a Gitea pull request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            base_url = "/".join(repo_url.split("/")[:-2])
            owner_repo = "/".join(repo_url.split("/")[-2:])

            api_url = f"{base_url}/api/v1/repos/{owner_repo}/pulls"

            headers = {
                "Authorization": f"token {self.settings.git_token}",
            }

            data = {
                "title": title,
                "body": description,
                "head": branch_name,
                "base": self.settings.git_branch,
            }

            response = await request_with_retry(
                "POST",
                api_url,
                headers=headers,
                json=data,
                timeout=30,
                retries=self.retries,
            )
            if response.status_code == 201:
                pr_data = response.json()
                logger.info(
                    "Created Gitea PR",
                    extra={
                        "pr_number": pr_data.get("number"),
                        "url": pr_data.get("html_url"),
                    },
                )
                return pr_data
            else:
                logger.error(
                    "Failed to create Gitea PR",
                    extra={
                        "status": response.status_code,
                        "response": response.text,
                    },
                )
                return None
        except Exception as e:
            logger.error("Error creating Gitea PR", extra={"error": str(e)})
            return None

    def cleanup(self) -> None:
        """Clean up cloned repository."""
        if self.repo_path and self.repo_path.exists():
            try:
                shutil.rmtree(self.repo_path)
                logger.info("Cleaned up Git repository", extra={"path": str(self.repo_path)})
            except Exception as e:
                logger.error("Failed to cleanup Git repo", extra={"error": str(e)})


_git_manager: GitManager | None = None


def get_git_manager() -> GitManager:
    """Get the global Git manager instance."""
    global _git_manager
    if _git_manager is None:
        _git_manager = GitManager()
    return _git_manager

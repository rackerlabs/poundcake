"""Runtime sync of bootstrap recipe catalog files from a remote Git repository."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from api.core.config import get_settings
from api.core.logging import get_logger
from api.services.bootstrap_recipe_catalog import load_bootstrap_recipe_catalog

logger = get_logger(__name__)

MANAGED_DESCRIPTION_PREFIX = "Bootstrap-managed remote recipe for alert rule"


class BootstrapRemoteRecipeSyncError(RuntimeError):
    """Raised when remote bootstrap recipe preparation cannot complete."""


def is_managed_bootstrap_recipe_description(description: str | None) -> bool:
    """Return whether a recipe description belongs to bootstrap-managed remote sync."""
    if not isinstance(description, str):
        return False
    return description.startswith(MANAGED_DESCRIPTION_PREFIX) or description.startswith(
        "Bootstrap-generated recipe for alert group "
    )


def slugify_recipe_filename(value: str) -> str:
    """Normalize a recipe name into a stable file name."""
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized or "recipe"


def render_managed_recipe_payload(
    *,
    alert_name: str,
    rule_hash: str,
) -> dict[str, Any]:
    """Build a runtime bootstrap recipe catalog entry for a single alert rule."""
    return {
        "apiVersion": "poundcake/v1",
        "kind": "RecipeCatalogEntry",
        "recipe": {
            "name": alert_name,
            "description": (
                f"{MANAGED_DESCRIPTION_PREFIX} {alert_name} " f"[source-sha256:{rule_hash[:12]}]"
            ),
            "enabled": True,
            "recipe_ingredients": [
                {
                    "execution_engine": "bakery",
                    "execution_target": "core",
                    "step_order": 1,
                    "run_phase": "resolving",
                    "on_success": "continue",
                    "parallel_group": 0,
                    "depth": 0,
                    "execution_parameters_override": None,
                }
            ],
        },
    }


def _load_git_module() -> Any:
    try:
        return importlib.import_module("git")
    except ImportError as exc:
        raise BootstrapRemoteRecipeSyncError(f"Git repository support unavailable: {exc}") from exc


def _credentialed_repo_url(*, repo_url: str, git_token: str) -> str:
    """Embed HTTPS token credentials into the repo URL when supported."""
    if not git_token or not repo_url.startswith("https://"):
        return repo_url
    if "github.com" in repo_url:
        return repo_url.replace("https://", f"https://x-access-token:{git_token}@")
    if "gitlab.com" in repo_url:
        return repo_url.replace("https://", f"https://oauth2:{git_token}@")
    return repo_url


def _get_git_env(*, repo_url: str, git_token: str, git_ssh_key_path: str) -> dict[str, str]:
    """Build Git environment variables for token and SSH-key backed access."""
    env = os.environ.copy()

    if git_token:
        if "github.com" in repo_url:
            env["GIT_ASKPASS"] = "echo"
            env["GIT_USERNAME"] = "oauth2"
            env["GIT_PASSWORD"] = git_token
        elif "gitlab.com" in repo_url:
            env["GIT_ASKPASS"] = "echo"
            env["GIT_USERNAME"] = "oauth2"
            env["GIT_PASSWORD"] = git_token

    if git_ssh_key_path:
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {git_ssh_key_path} -o StrictHostKeyChecking=no"
        )

    return env


def _ensure_repo_checkout(
    *,
    repo_url: str,
    branch: str,
) -> Path:
    git = _load_git_module()
    settings = get_settings()
    git_token = str(settings.git_token or "").strip()
    git_ssh_key_path = str(settings.git_ssh_key_path or "").strip()
    credentialed_repo_url = _credentialed_repo_url(repo_url=repo_url, git_token=git_token)
    git_env = _get_git_env(
        repo_url=repo_url,
        git_token=git_token,
        git_ssh_key_path=git_ssh_key_path,
    )
    work_dir = Path(tempfile.gettempdir()) / "poundcake-bootstrap-rules"
    work_dir.mkdir(parents=True, exist_ok=True)
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") or "bootstrap-rules"
    repo_path = work_dir / repo_name
    try:
        if repo_path.exists():
            repo = git.Repo(repo_path)
            origin = repo.remotes.origin
            if credentialed_repo_url != repo_url:
                origin.set_url(credentialed_repo_url)
            origin.fetch(env=git_env)
            try:
                repo.git.checkout(branch)
            except Exception:
                repo.git.checkout("-B", branch, f"origin/{branch}")
            origin.pull(branch, env=git_env)
        else:
            git.Repo.clone_from(credentialed_repo_url, repo_path, branch=branch, env=git_env)
    except Exception as exc:  # noqa: BLE001
        raise BootstrapRemoteRecipeSyncError(
            f"failed to clone/pull bootstrap rules repo '{repo_url}' branch '{branch}': {exc}"
        ) from exc
    return repo_path


def _iter_yaml_documents(path: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    try:
        raw_docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        raise BootstrapRemoteRecipeSyncError(f"failed to parse yaml file '{path}': {exc}") from exc

    for raw in raw_docs:
        if isinstance(raw, dict):
            docs.append(raw)
    return docs


def _extract_groups(document: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    direct_groups = document.get("groups")
    if isinstance(direct_groups, list):
        groups.extend(item for item in direct_groups if isinstance(item, dict))

    spec = document.get("spec")
    if isinstance(spec, dict) and isinstance(spec.get("groups"), list):
        groups.extend(item for item in spec["groups"] if isinstance(item, dict))

    rule_map = document.get("additionalPrometheusRulesMap")
    if isinstance(rule_map, dict):
        for value in rule_map.values():
            if isinstance(value, dict) and isinstance(value.get("groups"), list):
                groups.extend(item for item in value["groups"] if isinstance(item, dict))
    return groups


def _discover_alert_rules(source_dir: Path) -> tuple[dict[str, dict[str, Any]], int]:
    discovered: dict[str, dict[str, Any]] = {}
    files_scanned = 0
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        files_scanned += 1
        for document in _iter_yaml_documents(path):
            for group in _extract_groups(document):
                rules = group.get("rules")
                if not isinstance(rules, list):
                    continue
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    alert_name = rule.get("alert")
                    if not isinstance(alert_name, str) or not alert_name:
                        continue
                    canonical_rule = json.loads(json.dumps(rule, sort_keys=True))
                    rule_hash = hashlib.sha256(
                        json.dumps(canonical_rule, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    payload = {
                        "alert_name": alert_name,
                        "source_file": str(path.relative_to(source_dir)),
                        "rule_hash": rule_hash,
                    }
                    existing = discovered.get(alert_name)
                    if existing is None:
                        discovered[alert_name] = payload
                        continue
                    if existing["rule_hash"] != rule_hash:
                        raise BootstrapRemoteRecipeSyncError(
                            f"duplicate alert rule '{alert_name}' discovered with conflicting definitions"
                        )
    return discovered, files_scanned


def _write_generated_recipes(
    *,
    destination_dir: Path,
    alert_rules: dict[str, dict[str, Any]],
) -> int:
    destination_dir.mkdir(parents=True, exist_ok=True)
    for alert_name, payload in sorted(alert_rules.items()):
        recipe_payload = render_managed_recipe_payload(
            alert_name=alert_name,
            rule_hash=payload["rule_hash"],
        )
        target = destination_dir / f"{slugify_recipe_filename(alert_name)}.yaml"
        target.write_text(yaml.safe_dump(recipe_payload, sort_keys=False), encoding="utf-8")
    return len(alert_rules)


def _promote_generated_directory(*, temp_dir: Path, destination_dir: Path) -> None:
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = destination_dir.parent / f".{destination_dir.name}.bak"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if destination_dir.exists():
        destination_dir.rename(backup_dir)
    try:
        shutil.move(str(temp_dir), str(destination_dir))
    except Exception:
        if backup_dir.exists() and not destination_dir.exists():
            backup_dir.rename(destination_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)


def refresh_bootstrap_recipe_catalog_from_remote(
    *,
    repo_url: str,
    branch: str,
    rules_path: str,
    destination_dir: str,
) -> dict[str, Any]:
    """Clone/pull the remote rules repo, render recipes, validate, and promote atomically."""
    repo_path = _ensure_repo_checkout(repo_url=repo_url, branch=branch)
    source_dir = repo_path / str(rules_path).strip("/")
    if not source_dir.exists() or not source_dir.is_dir():
        raise BootstrapRemoteRecipeSyncError(
            f"bootstrap rules path not found in repo checkout: {source_dir}"
        )

    alert_rules, files_scanned = _discover_alert_rules(source_dir)
    temp_dir = Path(tempfile.mkdtemp(prefix="poundcake-bootstrap-recipes-"))
    try:
        generated_count = _write_generated_recipes(
            destination_dir=temp_dir,
            alert_rules=alert_rules,
        )
        _, validation_errors = load_bootstrap_recipe_catalog(str(temp_dir))
        if validation_errors:
            raise BootstrapRemoteRecipeSyncError(
                "generated bootstrap recipe catalog validation failed: "
                + "; ".join(validation_errors)
            )
        _promote_generated_directory(temp_dir=temp_dir, destination_dir=Path(destination_dir))
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(
        "Refreshed bootstrap recipe catalog from remote repo",
        extra={
            "repo_url": repo_url,
            "branch": branch,
            "rules_path": rules_path,
            "destination_dir": destination_dir,
            "files_scanned": files_scanned,
            "rules_discovered": len(alert_rules),
        },
    )
    return {
        "enabled": True,
        "refreshed": True,
        "files_scanned": files_scanned,
        "rules_discovered": len(alert_rules),
        "generated": generated_count,
        "source": destination_dir,
        "repo_url": repo_url,
        "branch": branch,
        "path": rules_path,
        "errors": 0,
        "error_messages": [],
    }

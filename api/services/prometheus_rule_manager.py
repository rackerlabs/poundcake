# ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Prometheus rule manager for editing and applying rule changes."""

import re
from pathlib import Path
from typing import Any

import yaml

from api.core.config import get_settings
from api.core.logging import get_logger
from api.services.alert_rule_repo import (
    ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
    AlertRuleSource,
    build_alert_rule_repo_index,
    delete_rule_from_document,
    document_has_rules,
    dump_alert_rule_document,
    infer_document_source,
    load_repo_documents,
    looks_like_repo_relative_rule_path,
    normalize_repo_relative_path,
    upsert_rule_in_document,
)
from api.services.git_manager import get_git_manager
from api.services.prometheus_service import get_prometheus_client
from api.services.prometheus_crd_manager import get_prometheus_crd_manager

logger = get_logger(__name__)


def normalize_rule_data(rule_name: str, rule_data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize incoming rule payload to PrometheusRule schema.

    Handles legacy UI/client payloads and strips unknown fields that are rejected
    by the PrometheusRule admission webhook.
    """
    normalized = dict(rule_data)

    # Backward-compat alias used by older UI payloads.
    if "alert" not in normalized and "order" in normalized:
        normalized["alert"] = normalized["order"]

    # Accept client-side alias while writing valid PrometheusRule schema.
    if "expr" not in normalized and "query" in normalized:
        normalized["expr"] = normalized["query"]

    # Ensure one of alert/record is always present for alert-rule workflows.
    if "alert" not in normalized and "record" not in normalized:
        normalized["alert"] = rule_name

    allowed_fields = {
        "alert",
        "record",
        "expr",
        "for",
        "labels",
        "annotations",
        "keep_firing_for",
    }
    cleaned: dict[str, Any] = {
        key: value
        for key, value in normalized.items()
        if key in allowed_fields and value is not None
    }
    return cleaned


def sanitize_crd_name(file_name: str) -> str:
    """
    Sanitize a file name to be a valid Kubernetes resource name.

    Kubernetes resource names must follow RFC 1123 subdomain rules:
    - Only lowercase alphanumeric characters, '-' or '.'
    - Must start and end with an alphanumeric character
    - Max 253 characters

    Args:
        file_name: The file name or path to sanitize

    Returns:
        A valid Kubernetes resource name
    """
    # Remove file extensions
    name = file_name.replace(".yaml", "").replace(".yml", "")

    # Extract just the basename if it's a full path
    if "/" in name:
        name = name.split("/")[-1]

    # Convert to lowercase
    name = name.lower()

    # Replace invalid characters with hyphens
    # Valid chars are: lowercase letters, digits, '-', '.'
    name = re.sub(r"[^a-z0-9.-]", "-", name)

    # Remove leading/trailing non-alphanumeric characters
    name = re.sub(r"^[^a-z0-9]+", "", name)
    name = re.sub(r"[^a-z0-9]+$", "", name)

    # Ensure it's not empty
    if not name:
        name = "prometheus-rule"

    # Truncate to 253 characters
    if len(name) > 253:
        name = name[:253].rstrip("-.")

    return name


class PrometheusRuleManager:
    """Manages Prometheus alert rule editing and GitOps workflow."""

    def __init__(self) -> None:
        """Initialize the rule manager."""
        self.settings = get_settings()
        self.git_manager = get_git_manager()
        self.prometheus = get_prometheus_client()
        self.crd_manager = get_prometheus_crd_manager()

    def _get_file_path(
        self,
        rule_name: str,
        group_name: str,
        crd_name: str,
    ) -> str:
        """
        Get the file path for a rule based on configuration.

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            crd_name: Name of the CRD

        Returns:
            File path relative to git_rules_path
        """
        if self.settings.git_file_per_alert:
            filename = self.settings.git_file_pattern.format(
                alert_name=rule_name,
                group_name=group_name,
                crd_name=crd_name,
            )
            return filename
        else:
            return crd_name if crd_name.endswith((".yaml", ".yml")) else f"{crd_name}.yaml"

    def _source_from_file_name(self, file_name: str) -> AlertRuleSource | None:
        raw = str(file_name or "").strip()
        if not raw or not looks_like_repo_relative_rule_path(raw):
            return None
        try:
            return AlertRuleSource(relative_path=normalize_repo_relative_path(raw))
        except ValueError:
            return None

    async def _load_git_rule_context(
        self,
    ) -> tuple[str, Path, Any]:
        if not await self.git_manager.clone_or_pull():
            raise RuntimeError("Failed to clone/pull Git repository")

        assert self.git_manager.repo_path is not None
        try:
            rules_dir = normalize_repo_relative_path(str(self.settings.git_rules_path or ""))
        except ValueError as exc:
            raise RuntimeError(f"Git rules directory {exc}") from exc

        base_dir = self.git_manager.repo_path / rules_dir
        try:
            repo_index = build_alert_rule_repo_index(base_dir)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        return rules_dir, base_dir, repo_index

    def _load_single_git_rule_document(self, path: Path) -> Any:
        documents = load_repo_documents(path)
        if len(documents) != 1:
            raise RuntimeError(
                f"Alert-rule file '{path.name}' must contain exactly one document for direct edits"
            )
        return documents[0]

    async def _resolve_git_update_source(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> tuple[str, Path, AlertRuleSource]:
        rules_dir, base_dir, repo_index = await self._load_git_rule_context()
        repo_entry = repo_index.by_alert_name.get(rule_name)
        explicit_source = self._source_from_file_name(file_name)

        if repo_entry is not None:
            if group_name.strip() != repo_entry.group_name:
                raise RuntimeError(
                    "Changing a rule group via update creates a new rule; use create instead"
                )
            if (
                explicit_source is not None
                and explicit_source.relative_path != repo_entry.source.relative_path
            ):
                raise RuntimeError(
                    "Changing a rule source path via update creates a new rule; use create instead"
                )
            return rules_dir, base_dir, repo_entry.source

        if explicit_source is None:
            legacy_source = AlertRuleSource(
                relative_path=self._get_file_path(
                    rule_name,
                    group_name,
                    sanitize_crd_name(file_name or rule_name),
                )
            )
            full_path = base_dir / legacy_source.relative_path
            if full_path.exists():
                document = self._load_single_git_rule_document(full_path)
                document_source = infer_document_source(document, legacy_source.relative_path)
                if document_source is None:
                    raise RuntimeError(
                        f"Rule file '{rules_dir}/{legacy_source.relative_path}' does not contain supported alert-rule groups"
                    )
                return rules_dir, base_dir, document_source
            raise RuntimeError(f"Rule '{rule_name}' not found in Git repository")

        full_path = base_dir / explicit_source.relative_path
        if not full_path.exists():
            raise RuntimeError(f"Rule file not found: {rules_dir}/{explicit_source.relative_path}")

        document = self._load_single_git_rule_document(full_path)
        document_source = infer_document_source(document, explicit_source.relative_path)
        if document_source is None:
            raise RuntimeError(
                f"Rule file '{rules_dir}/{explicit_source.relative_path}' does not contain supported alert-rule groups"
            )
        return rules_dir, base_dir, document_source

    async def _resolve_git_create_source(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> tuple[str, Path, AlertRuleSource]:
        rules_dir, base_dir, repo_index = await self._load_git_rule_context()
        if rule_name in repo_index.by_alert_name:
            raise RuntimeError(f"Rule '{rule_name}' already exists in Git repository")

        source = self._source_from_file_name(file_name)
        if source is None:
            file_hint = sanitize_crd_name(file_name or rule_name)
            source = AlertRuleSource(
                relative_path=self._get_file_path(rule_name, group_name, file_hint),
                source_format=ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
            )

        full_path = base_dir / source.relative_path
        if full_path.exists():
            document = self._load_single_git_rule_document(full_path)
            inferred = infer_document_source(document, source.relative_path)
            if inferred is None:
                raise RuntimeError(
                    f"Rule file '{rules_dir}/{source.relative_path}' does not contain supported alert-rule groups"
                )
            source = inferred

        return rules_dir, base_dir, source

    async def _resolve_git_delete_source(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> tuple[str, Path, AlertRuleSource]:
        rules_dir, base_dir, repo_index = await self._load_git_rule_context()
        repo_entry = repo_index.by_alert_name.get(rule_name)
        if repo_entry is not None:
            return rules_dir, base_dir, repo_entry.source

        explicit_source = self._source_from_file_name(file_name)
        if explicit_source is None:
            legacy_source = AlertRuleSource(
                relative_path=self._get_file_path(
                    rule_name,
                    group_name=group_name,
                    crd_name=sanitize_crd_name(file_name or rule_name),
                )
            )
            full_path = base_dir / legacy_source.relative_path
            if full_path.exists():
                document = self._load_single_git_rule_document(full_path)
                document_source = infer_document_source(document, legacy_source.relative_path)
                if document_source is None:
                    raise RuntimeError(
                        f"Rule file '{rules_dir}/{legacy_source.relative_path}' does not contain supported alert-rule groups"
                    )
                return rules_dir, base_dir, document_source
            raise RuntimeError(f"Rule '{rule_name}' not found in Git repository")

        full_path = base_dir / explicit_source.relative_path
        if not full_path.exists():
            raise RuntimeError(f"Rule file not found: {rules_dir}/{explicit_source.relative_path}")

        document = self._load_single_git_rule_document(full_path)
        document_source = infer_document_source(document, explicit_source.relative_path)
        if document_source is None:
            raise RuntimeError(
                f"Rule file '{rules_dir}/{explicit_source.relative_path}' does not contain supported alert-rule groups"
            )
        return rules_dir, base_dir, document_source

    async def update_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update a Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Updates PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Updates Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name
            rule_data: Updated rule configuration

        Returns:
            Result of the update operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule updated",
        }
        normalized_rule_data = normalize_rule_data(rule_name, rule_data)
        git_source: AlertRuleSource | None = None

        if self.settings.git_enabled:
            try:
                _rules_dir, _base_dir, git_source = await self._resolve_git_update_source(
                    rule_name,
                    group_name,
                    file_name,
                )
            except RuntimeError as exc:
                return {
                    "status": "error",
                    "message": str(exc),
                }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = sanitize_crd_name(
                git_source.relative_path if git_source is not None else file_name
            )
            crd_result = await self.crd_manager.create_or_update_rule(
                rule_name,
                group_name,
                crd_name,
                normalized_rule_data,
                source_metadata=git_source,
            )

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Updated rule in CRD",
                extra={
                    "rule": rule_name,
                    "crd": crd_name,
                    "action": crd_result.get("action"),
                },
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._update_rule_in_git(
                rule_name, group_name, file_name, normalized_rule_data
            )

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule updated in CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _update_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a rule in Git repository."""

        try:
            rules_dir, base_dir, source = await self._resolve_git_update_source(
                rule_name,
                group_name,
                file_name,
            )
            full_path = base_dir / source.relative_path
            document = self._load_single_git_rule_document(full_path)
            updated_document = upsert_rule_in_document(
                document,
                source=source,
                group_name=group_name,
                rule_name=rule_name,
                rule_data=rule_data,
            )
            updated_yaml = dump_alert_rule_document(updated_document, source.relative_path)
            file_path = f"{rules_dir}/{source.relative_path}"

            commit_message = (
                f"Update Prometheus alert rule: {rule_name}\n\n"
                f"Updated by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {source.relative_path}"
            )

            success, branch_name = await self.git_manager.commit_and_push_changes(
                file_path, updated_yaml, commit_message
            )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule updated in Git",
                "branch": branch_name,
            }

            pr_title = f"Update Prometheus alert: {rule_name}"
            pr_description = (
                f"## Alert Rule Update\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{source.relative_path}`\n\n"
                f"Updated via PoundCake UI.\n\n"
                f"### Changes\n"
                f"```yaml\n{yaml.dump(rule_data, default_flow_style=False)}\n```"
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Updated Prometheus rule",
                extra={"rule": rule_name, "group": group_name, "branch": branch_name},
            )

            return result
        except Exception as e:
            logger.error("Error updating Prometheus rule", extra={"error": str(e)})
            return {
                "status": "error",
                "message": str(e),
            }

    async def create_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a new Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Creates in PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Creates in Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name
            rule_data: Rule configuration

        Returns:
            Result of the create operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule created",
        }
        normalized_rule_data = normalize_rule_data(rule_name, rule_data)
        git_source: AlertRuleSource | None = None

        if self.settings.git_enabled:
            try:
                _rules_dir, _base_dir, git_source = await self._resolve_git_create_source(
                    rule_name,
                    group_name,
                    file_name,
                )
            except RuntimeError as exc:
                return {
                    "status": "error",
                    "message": str(exc),
                }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = sanitize_crd_name(
                git_source.relative_path if git_source is not None else file_name
            )
            crd_result = await self.crd_manager.create_or_update_rule(
                rule_name,
                group_name,
                crd_name,
                normalized_rule_data,
                source_metadata=git_source,
            )

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Created rule in CRD",
                extra={
                    "rule": rule_name,
                    "crd": crd_name,
                    "action": crd_result.get("action"),
                },
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._create_rule_in_git(
                rule_name, group_name, file_name, normalized_rule_data
            )

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule created in CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _create_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a rule in Git repository."""

        try:
            rules_dir, base_dir, source = await self._resolve_git_create_source(
                rule_name,
                group_name,
                file_name,
            )
            full_path = base_dir / source.relative_path
            document: Any
            if full_path.exists():
                document = self._load_single_git_rule_document(full_path)
            else:
                document = {}
            updated_document = upsert_rule_in_document(
                document,
                source=source,
                group_name=group_name,
                rule_name=rule_name,
                rule_data=rule_data,
            )
            updated_yaml = dump_alert_rule_document(updated_document, source.relative_path)
            file_path = f"{rules_dir}/{source.relative_path}"

            commit_message = (
                f"Add Prometheus alert rule: {rule_name}\n\n"
                f"Created by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {source.relative_path}"
            )

            success, branch_name = await self.git_manager.commit_and_push_changes(
                file_path, updated_yaml, commit_message
            )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule created in Git",
                "branch": branch_name,
            }

            pr_title = f"Add Prometheus alert: {rule_name}"
            pr_description = (
                f"## New Alert Rule\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{source.relative_path}`\n\n"
                f"Created via PoundCake UI.\n\n"
                f"### Rule Definition\n"
                f"```yaml\n{yaml.dump(rule_data, default_flow_style=False)}\n```"
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Created Prometheus rule",
                extra={"rule": rule_name, "group": group_name, "branch": branch_name},
            )

            return result
        except Exception as e:
            logger.error("Error creating Prometheus rule", extra={"error": str(e)})
            return {
                "status": "error",
                "message": str(e),
            }

    async def delete_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> dict[str, Any]:
        """
        Delete a Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Deletes from PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Deletes from Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name

        Returns:
            Result of the delete operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule deleted",
        }
        git_source: AlertRuleSource | None = None

        if self.settings.git_enabled:
            try:
                _rules_dir, _base_dir, git_source = await self._resolve_git_delete_source(
                    rule_name,
                    group_name,
                    file_name,
                )
            except RuntimeError as exc:
                return {
                    "status": "error",
                    "message": str(exc),
                }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = sanitize_crd_name(
                git_source.relative_path if git_source is not None else file_name
            )
            crd_result = await self.crd_manager.delete_rule(rule_name, group_name, crd_name)

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Deleted rule from CRD",
                extra={
                    "rule": rule_name,
                    "crd": crd_name,
                    "action": crd_result.get("action"),
                },
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._delete_rule_in_git(rule_name, group_name, file_name)

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule deleted from CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _delete_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> dict[str, Any]:
        """Delete a rule from Git repository."""

        try:
            rules_dir, base_dir, source = await self._resolve_git_delete_source(
                rule_name,
                group_name,
                file_name,
            )
            file_path = f"{rules_dir}/{source.relative_path}"
            full_path = base_dir / source.relative_path
            document = self._load_single_git_rule_document(full_path)
            updated_document, deleted = delete_rule_from_document(
                document,
                source=source,
                group_name=group_name,
                rule_name=rule_name,
            )
            if not deleted:
                return {
                    "status": "error",
                    "message": f"Rule {rule_name} not found in group {group_name}",
                }

            commit_message = (
                f"Delete Prometheus alert rule: {rule_name}\n\n"
                f"Deleted by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {source.relative_path}"
            )

            if not document_has_rules(updated_document):
                success, branch_name = await self.git_manager.commit_and_push_deletion(
                    file_path,
                    commit_message,
                )
            else:
                updated_yaml = dump_alert_rule_document(updated_document, source.relative_path)
                success, branch_name = await self.git_manager.commit_and_push_changes(
                    file_path,
                    updated_yaml,
                    commit_message,
                )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule deleted from Git",
                "branch": branch_name,
            }

            pr_title = f"Delete Prometheus alert: {rule_name}"
            pr_description = (
                f"## Delete Alert Rule\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{source.relative_path}`\n\n"
                f"Deleted via PoundCake UI."
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Deleted Prometheus rule",
                extra={"rule": rule_name, "group": group_name, "branch": branch_name},
            )

            return result
        except Exception as e:
            logger.error("Error deleting Prometheus rule", extra={"error": str(e)})
            return {
                "status": "error",
                "message": str(e),
            }


_rule_manager: PrometheusRuleManager | None = None


def get_prometheus_rule_manager() -> PrometheusRuleManager:
    """Get the global Prometheus rule manager instance."""
    global _rule_manager
    if _rule_manager is None:
        _rule_manager = PrometheusRuleManager()
    return _rule_manager

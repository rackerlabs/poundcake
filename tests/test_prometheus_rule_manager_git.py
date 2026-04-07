from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services.prometheus_rule_manager import PrometheusRuleManager


class _FakeGitManager:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self.last_changes: dict[str, str | None] | None = None
        self.last_commit_message: str | None = None

    async def clone_or_pull(self) -> bool:
        return True

    async def commit_and_push_changes(
        self,
        file_path: str,
        content: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        self.last_changes = {file_path: content}
        self.last_commit_message = commit_message
        return True, "poundcake-rule-update-1234"

    async def commit_and_push_deletion(
        self,
        file_path: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        self.last_changes = {file_path: None}
        self.last_commit_message = commit_message
        return True, "poundcake-rule-update-1234"

    async def create_pull_request(
        self,
        branch_name: str,
        title: str,
        description: str,
    ) -> dict[str, object]:
        return {"number": 7, "html_url": "https://example.test/pr/7"}


def _manager(tmp_path: Path) -> PrometheusRuleManager:
    manager = PrometheusRuleManager()
    manager.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_file_per_alert=True,
        git_file_pattern="{alert_name}.yaml",
        prometheus_use_crds=False,
    )
    manager.git_manager = _FakeGitManager(tmp_path)
    return manager


def _write_wrapped_rule_file(
    path: Path, *, wrapper_key: str, group_name: str, rules: list[dict]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    wrapper_key: {
                        "groups": [
                            {
                                "name": group_name,
                                "rules": rules,
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_update_rule_updates_existing_wrapped_repo_file_in_place(tmp_path: Path) -> None:
    _write_wrapped_rule_file(
        tmp_path / "alerts" / "kubernetes" / "kube-api-down.yaml",
        wrapper_key="kube-api-down",
        group_name="kube-api-down",
        rules=[{"alert": "kube-api-down-warning", "expr": "up == 0"}],
    )
    manager = _manager(tmp_path)

    result = await manager.update_rule(
        "kube-api-down-warning",
        "kube-api-down",
        "kubernetes/kube-api-down.yaml",
        {"alert": "kube-api-down-warning", "expr": "up == 1"},
    )

    assert result["status"] == "success"
    assert manager.git_manager.last_changes is not None
    assert list(manager.git_manager.last_changes) == ["alerts/kubernetes/kube-api-down.yaml"]
    payload = yaml.safe_load(
        manager.git_manager.last_changes["alerts/kubernetes/kube-api-down.yaml"]
    )
    assert list(payload["additionalPrometheusRulesMap"]) == ["kube-api-down"]
    assert (
        payload["additionalPrometheusRulesMap"]["kube-api-down"]["groups"][0]["rules"][0]["expr"]
        == "up == 1"
    )


@pytest.mark.asyncio
async def test_create_rule_appends_to_existing_wrapped_repo_file(tmp_path: Path) -> None:
    _write_wrapped_rule_file(
        tmp_path / "alerts" / "kubernetes" / "kube-api-down.yaml",
        wrapper_key="kube-api-down",
        group_name="kube-api-down",
        rules=[{"alert": "kube-api-down-warning", "expr": "up == 0"}],
    )
    manager = _manager(tmp_path)

    result = await manager.create_rule(
        "kube-api-down-critical",
        "kube-api-down",
        "kubernetes/kube-api-down.yaml",
        {"alert": "kube-api-down-critical", "expr": "up == 2"},
    )

    assert result["status"] == "success"
    assert manager.git_manager.last_changes is not None
    assert list(manager.git_manager.last_changes) == ["alerts/kubernetes/kube-api-down.yaml"]
    payload = yaml.safe_load(
        manager.git_manager.last_changes["alerts/kubernetes/kube-api-down.yaml"]
    )
    alerts = payload["additionalPrometheusRulesMap"]["kube-api-down"]["groups"][0]["rules"]
    assert [rule["alert"] for rule in alerts] == [
        "kube-api-down-warning",
        "kube-api-down-critical",
    ]


@pytest.mark.asyncio
async def test_create_rule_uses_requested_repo_path_for_new_wrapped_file(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    result = await manager.create_rule(
        "fresh-alert-warning",
        "fresh-alert",
        "kubernetes/fresh-alert.yaml",
        {"alert": "fresh-alert-warning", "expr": "up == 3"},
    )

    assert result["status"] == "success"
    assert manager.git_manager.last_changes is not None
    assert list(manager.git_manager.last_changes) == ["alerts/kubernetes/fresh-alert.yaml"]
    payload = yaml.safe_load(manager.git_manager.last_changes["alerts/kubernetes/fresh-alert.yaml"])
    assert list(payload["additionalPrometheusRulesMap"]) == ["fresh-alert"]
    assert (
        payload["additionalPrometheusRulesMap"]["fresh-alert"]["groups"][0]["rules"][0]["alert"]
        == "fresh-alert-warning"
    )


@pytest.mark.asyncio
async def test_delete_rule_removes_wrapped_file_when_last_rule_is_deleted(tmp_path: Path) -> None:
    _write_wrapped_rule_file(
        tmp_path / "alerts" / "kubernetes" / "kube-api-down.yaml",
        wrapper_key="kube-api-down",
        group_name="kube-api-down",
        rules=[{"alert": "kube-api-down-warning", "expr": "up == 0"}],
    )
    manager = _manager(tmp_path)

    result = await manager.delete_rule(
        "kube-api-down-warning",
        "kube-api-down",
        "kubernetes/kube-api-down.yaml",
    )

    assert result["status"] == "success"
    assert manager.git_manager.last_changes == {"alerts/kubernetes/kube-api-down.yaml": None}

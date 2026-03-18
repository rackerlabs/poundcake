from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from api.services.repo_sync_service import RepoSyncService


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def unique(self):
        return self


class _FakeGitManager:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self.last_changes: dict[str, str | None] | None = None
        self.last_commit_message: str | None = None

    async def clone_or_pull(self) -> bool:
        return True

    async def commit_and_push_files(
        self,
        changes: dict[str, str | None],
        commit_message: str,
        *,
        branch_prefix: str = "poundcake-sync",
    ) -> tuple[bool, str]:
        self.last_changes = changes
        self.last_commit_message = commit_message
        return True, "poundcake-sync-1234"

    async def create_pull_request(
        self,
        branch_name: str,
        title: str,
        description: str,
    ) -> dict[str, object]:
        return {"number": 7, "html_url": "https://example.test/pr/7"}


@pytest.mark.asyncio
async def test_export_workflow_actions_writes_portable_yaml(tmp_path: Path) -> None:
    action = SimpleNamespace(
        id=11,
        execution_target="core.remote",
        destination_target="",
        task_key_template="restart_service",
        execution_engine="stackstorm",
        execution_purpose="remediation",
        execution_id="core.remote",
        execution_payload=None,
        execution_parameters={"hosts": "{{instance}}"},
        is_default=False,
        is_blocking=True,
        expected_duration_sec=60,
        timeout_duration_sec=300,
        retry_count=0,
        retry_delay=5,
        on_failure="stop",
    )
    step = SimpleNamespace(
        step_order=1,
        on_success="continue",
        parallel_group=0,
        depth=0,
        execution_parameters_override={"service": "nginx"},
        run_phase="firing",
        run_condition="always",
        ingredient=action,
    )
    workflow = SimpleNamespace(
        id=21,
        name="Node service response",
        description="Restart a stuck service",
        enabled=True,
        clear_timeout_sec=300,
        recipe_ingredients=[step],
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([action]), _ScalarResult([workflow])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="poundcake/actions",
        git_workflows_path="poundcake/workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    result = await service.export_workflow_actions()

    assert result["status"] == "success"
    assert result["exported"]["actions"] == 1
    assert result["exported"]["workflows"] == 1
    assert service.git_manager.last_changes is not None
    action_paths = [
        path for path in service.git_manager.last_changes if path.startswith("poundcake/actions/")
    ]
    workflow_paths = [
        path for path in service.git_manager.last_changes if path.startswith("poundcake/workflows/")
    ]
    assert len(action_paths) == 1
    assert len(workflow_paths) == 1

    action_doc = yaml.safe_load(service.git_manager.last_changes[action_paths[0]])
    workflow_doc = yaml.safe_load(service.git_manager.last_changes[workflow_paths[0]])
    assert action_doc["kind"] == "action"
    assert action_doc["action"]["task_key_template"] == "restart_service"
    assert workflow_doc["kind"] == "workflow"
    assert (
        workflow_doc["workflow"]["recipe_ingredients"][0]["action"]["task_key_template"]
        == "restart_service"
    )
    assert "ingredient_id" not in workflow_doc["workflow"]["recipe_ingredients"][0]


@pytest.mark.asyncio
async def test_export_workflow_actions_handles_zero_step_workflow(tmp_path: Path) -> None:
    workflow = SimpleNamespace(
        id=21,
        name="Communications only workflow",
        description="No visible action steps yet",
        enabled=True,
        clear_timeout_sec=300,
        recipe_ingredients=[],
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([]), _ScalarResult([workflow])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="poundcake/actions",
        git_workflows_path="poundcake/workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    result = await service.export_workflow_actions()

    assert result["status"] == "success"
    assert result["exported"]["actions"] == 0
    assert result["exported"]["workflows"] == 1
    assert service.git_manager.last_changes is not None
    workflow_paths = [
        path for path in service.git_manager.last_changes if path.startswith("poundcake/workflows/")
    ]
    assert len(workflow_paths) == 1

    workflow_doc = yaml.safe_load(service.git_manager.last_changes[workflow_paths[0]])
    assert workflow_doc["kind"] == "workflow"
    assert workflow_doc["workflow"]["recipe_ingredients"] == []


@pytest.mark.asyncio
async def test_import_workflow_actions_resolves_portable_action_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_dir = tmp_path / "workflows"
    shared_dir.mkdir(parents=True)
    (shared_dir / "restart_service.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "action",
                "action": {
                    "task_key_template": "restart_service",
                    "execution_target": "core.remote",
                    "destination_target": "",
                    "execution_engine": "stackstorm",
                    "execution_purpose": "remediation",
                    "execution_id": "core.remote",
                    "execution_parameters": {"hosts": "{{instance}}"},
                    "is_default": False,
                    "is_blocking": True,
                    "expected_duration_sec": 60,
                    "timeout_duration_sec": 300,
                    "retry_count": 0,
                    "retry_delay": 5,
                    "on_failure": "stop",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (shared_dir / "node_service_response.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "workflow",
                "workflow": {
                    "name": "Node service response",
                    "description": "Restart a stuck service",
                    "enabled": True,
                    "clear_timeout_sec": 300,
                    "communications": {"mode": "inherit", "routes": []},
                    "recipe_ingredients": [
                        {
                            "step_order": 1,
                            "on_success": "continue",
                            "parallel_group": 0,
                            "depth": 0,
                            "execution_parameters_override": {"service": "nginx"},
                            "run_phase": "firing",
                            "run_condition": "always",
                            "action": {
                                "task_key_template": "restart_service",
                                "execution_target": "core.remote",
                                "destination_target": "",
                                "execution_engine": "stackstorm",
                            },
                        }
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([]), _ScalarResult([])])
    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_actions_path="workflows",
        git_workflows_path="workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    create_ingredient_mock = AsyncMock(
        return_value=SimpleNamespace(
            id=44,
            task_key_template="restart_service",
            execution_target="core.remote",
            destination_target="",
            execution_engine="stackstorm",
        )
    )
    create_recipe_mock = AsyncMock()
    monkeypatch.setattr("api.services.repo_sync_service.create_ingredient", create_ingredient_mock)
    monkeypatch.setattr("api.services.repo_sync_service.create_recipe", create_recipe_mock)

    result = await service.import_workflow_actions()

    assert result["status"] == "success"
    assert result["imported"]["actions_created"] == 1
    assert result["imported"]["workflows_created"] == 1
    create_ingredient_mock.assert_awaited_once()
    create_recipe_mock.assert_awaited_once()
    recipe_payload = create_recipe_mock.await_args.args[1]
    assert recipe_payload.recipe_ingredients[0].ingredient_id == 44


@pytest.mark.asyncio
async def test_import_workflow_actions_allows_zero_step_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "communications_only.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "workflow",
                "workflow": {
                    "name": "Communications only workflow",
                    "description": "No visible action steps yet",
                    "enabled": True,
                    "clear_timeout_sec": 300,
                    "communications": {"mode": "inherit", "routes": []},
                    "recipe_ingredients": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([]), _ScalarResult([])])
    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_actions_path="actions",
        git_workflows_path="workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    create_recipe_mock = AsyncMock()
    monkeypatch.setattr("api.services.repo_sync_service.create_recipe", create_recipe_mock)

    result = await service.import_workflow_actions()

    assert result["status"] == "success"
    assert result["imported"]["actions_created"] == 0
    assert result["imported"]["workflows_created"] == 1
    create_recipe_mock.assert_awaited_once()
    recipe_payload = create_recipe_mock.await_args.args[1]
    assert recipe_payload.recipe_ingredients == []


def test_runtime_dependencies_include_gitpython() -> None:
    pyproject = Path("pyproject.toml")
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert any(str(dep).lower().startswith("gitpython") for dep in dependencies)


@pytest.mark.asyncio
async def test_export_alert_rules_writes_files_into_rules_directory(tmp_path: Path) -> None:
    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="prometheus/rules",
        git_file_per_alert=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(
        return_value=[
            {
                "group": "node-filesystem",
                "file": "kubernetes-resources",
                "rule": {
                    "alert": "NodeFilesystemAlmostOutOfSpace",
                    "expr": "up == 0",
                    "for": "5m",
                    "labels": {"severity": "critical"},
                    "annotations": {"summary": "Disk almost full"},
                },
            }
        ]
    )

    result = await service.export_alert_rules()

    assert result["status"] == "success"
    assert result["exported"]["alert_rules"] == 1
    assert service.git_manager.last_changes is not None
    paths = [
        path for path in service.git_manager.last_changes if path.startswith("prometheus/rules/")
    ]
    assert len(paths) == 1
    payload = yaml.safe_load(service.git_manager.last_changes[paths[0]])
    assert payload["groups"][0]["name"] == "node-filesystem"
    assert payload["groups"][0]["rules"][0]["alert"] == "NodeFilesystemAlmostOutOfSpace"


@pytest.mark.asyncio
async def test_export_workflow_actions_supports_shared_directory(tmp_path: Path) -> None:
    shared_dir = tmp_path / "workflows"
    shared_dir.mkdir(parents=True)
    old_path = shared_dir / "obsolete.yaml"
    old_path.write_text("kind: action\n", encoding="utf-8")

    action = SimpleNamespace(
        id=11,
        execution_target="core.remote",
        destination_target="",
        task_key_template="restart_service",
        execution_engine="stackstorm",
        execution_purpose="remediation",
        execution_id="core.remote",
        execution_payload=None,
        execution_parameters={"hosts": "{{instance}}"},
        is_default=False,
        is_blocking=True,
        expected_duration_sec=60,
        timeout_duration_sec=300,
        retry_count=0,
        retry_delay=5,
        on_failure="stop",
    )
    step = SimpleNamespace(
        step_order=1,
        on_success="continue",
        parallel_group=0,
        depth=0,
        execution_parameters_override=None,
        run_phase="firing",
        run_condition="always",
        ingredient=action,
    )
    workflow = SimpleNamespace(
        id=21,
        name="Node service response",
        description="Restart a stuck service",
        enabled=True,
        clear_timeout_sec=300,
        recipe_ingredients=[step],
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([action]), _ScalarResult([workflow])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="workflows",
        git_workflows_path="workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    await service.export_workflow_actions()

    assert service.git_manager.last_changes is not None
    assert any(
        path.endswith(".yaml") and content is not None
        for path, content in service.git_manager.last_changes.items()
    )
    assert "workflows/obsolete.yaml" in service.git_manager.last_changes
    assert service.git_manager.last_changes["workflows/obsolete.yaml"] is None
    assert any(
        path.startswith("workflows/") and content is not None and "kind: action" in content
        for path, content in service.git_manager.last_changes.items()
        if content is not None
    )
    assert any(
        path.startswith("workflows/") and content is not None and "kind: workflow" in content
        for path, content in service.git_manager.last_changes.items()
        if content is not None
    )

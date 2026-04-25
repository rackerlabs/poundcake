from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from api.services.alert_rule_repo import ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP
from api.services.git_manager import GitManager
from api.services.repo_sync_service import RepoSyncError, RepoSyncService


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


@pytest.mark.asyncio
async def test_export_actions_writes_only_action_files(tmp_path: Path) -> None:
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
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([action])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="poundcake/actions",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    result = await service.export_actions()

    assert result["status"] == "success"
    assert result["exported"]["actions"] == 1
    assert service.git_manager.last_changes is not None
    action_paths = [
        path for path in service.git_manager.last_changes if path.startswith("poundcake/actions/")
    ]
    assert len(action_paths) == 1
    payload = yaml.safe_load(service.git_manager.last_changes[action_paths[0]])
    assert payload["kind"] == "action"


@pytest.mark.asyncio
async def test_export_workflows_writes_only_workflow_files(tmp_path: Path) -> None:
    action = SimpleNamespace(
        id=11,
        execution_target="core.remote",
        destination_target="",
        task_key_template="restart_service",
        execution_engine="stackstorm",
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
    db.execute = AsyncMock(side_effect=[_ScalarResult([workflow])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_workflows_path="poundcake/workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    result = await service.export_workflows()

    assert result["status"] == "success"
    assert result["exported"]["workflows"] == 1
    assert service.git_manager.last_changes is not None
    workflow_paths = [
        path for path in service.git_manager.last_changes if path.startswith("poundcake/workflows/")
    ]
    assert len(workflow_paths) == 1
    payload = yaml.safe_load(service.git_manager.last_changes[workflow_paths[0]])
    assert payload["kind"] == "workflow"


@pytest.mark.asyncio
async def test_import_actions_only_upserts_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir(parents=True)
    (actions_dir / "restart_service.yaml").write_text(
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
                    "is_active": True,
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

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([])])
    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_actions_path="actions",
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

    result = await service.import_actions()

    assert result["status"] == "success"
    assert result["imported"]["actions_created"] == 1
    assert result["imported"]["actions_updated"] == 0
    create_ingredient_mock.assert_awaited_once()
    create_recipe_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_workflows_skips_missing_actions_and_reports_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "node_service_response.yaml").write_text(
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
    (workflow_dir / "broken_workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "workflow",
                "workflow": {
                    "name": "Broken workflow",
                    "description": "References a missing action",
                    "enabled": True,
                    "communications": {"mode": "inherit", "routes": []},
                    "recipe_ingredients": [
                        {
                            "step_order": 1,
                            "on_success": "continue",
                            "parallel_group": 0,
                            "depth": 0,
                            "run_phase": "firing",
                            "run_condition": "always",
                            "action": {
                                "task_key_template": "missing_action",
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

    existing_action = SimpleNamespace(
        id=44,
        task_key_template="restart_service",
        execution_target="core.remote",
        destination_target="",
        execution_engine="stackstorm",
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([existing_action]), _ScalarResult([])])
    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_workflows_path="workflows",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    create_recipe_mock = AsyncMock()
    monkeypatch.setattr("api.services.repo_sync_service.create_recipe", create_recipe_mock)

    result = await service.import_workflows()

    assert result["status"] == "success"
    assert result["imported"]["workflows_created"] == 1
    assert result["imported"]["workflows_updated"] == 0
    assert result["skipped"]["workflows"] == 1
    assert "Skipped 1 workflow(s) with missing actions." in result["message"]
    assert any("Broken workflow" in warning for warning in result["warnings"])
    assert any("missing_action" in warning for warning in result["warnings"])
    create_recipe_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_actions_preserves_workflow_files_in_shared_directory(
    tmp_path: Path,
) -> None:
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "workflow",
                "workflow": {
                    "name": "Node service response",
                    "description": "Restart a stuck service",
                    "enabled": True,
                    "communications": {"mode": "inherit", "routes": []},
                    "recipe_ingredients": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (shared_dir / "obsolete-action.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "action",
                "action": {
                    "task_key_template": "obsolete_action",
                    "execution_target": "core.remote",
                    "destination_target": "",
                    "execution_engine": "stackstorm",
                    "execution_purpose": "remediation",
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
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([action])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="shared",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    await service.export_actions()

    assert service.git_manager.last_changes is not None
    assert "shared/obsolete-action.yaml" in service.git_manager.last_changes
    assert service.git_manager.last_changes["shared/obsolete-action.yaml"] is None
    assert "shared/workflow.yaml" not in service.git_manager.last_changes


@pytest.mark.asyncio
async def test_export_workflows_preserves_action_files_in_shared_directory(
    tmp_path: Path,
) -> None:
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "action.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "action",
                "action": {
                    "task_key_template": "restart_service",
                    "execution_target": "core.remote",
                    "destination_target": "",
                    "execution_engine": "stackstorm",
                    "execution_purpose": "remediation",
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
    (shared_dir / "obsolete-workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "workflow",
                "workflow": {
                    "name": "Obsolete workflow",
                    "enabled": True,
                    "communications": {"mode": "inherit", "routes": []},
                    "recipe_ingredients": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    action = SimpleNamespace(
        id=11,
        execution_target="core.remote",
        destination_target="",
        task_key_template="restart_service",
        execution_engine="stackstorm",
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
    db.execute = AsyncMock(side_effect=[_ScalarResult([workflow])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_workflows_path="shared",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    await service.export_workflows()

    assert service.git_manager.last_changes is not None
    assert "shared/obsolete-workflow.yaml" in service.git_manager.last_changes
    assert service.git_manager.last_changes["shared/obsolete-workflow.yaml"] is None
    assert "shared/action.yaml" not in service.git_manager.last_changes


@pytest.mark.asyncio
async def test_split_export_rejects_mixed_action_workflow_files(tmp_path: Path) -> None:
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "mixed.yaml").write_text(
        yaml.safe_dump(
            {
                "actions": [
                    {
                        "task_key_template": "restart_service",
                        "execution_target": "core.remote",
                        "destination_target": "",
                        "execution_engine": "stackstorm",
                        "execution_purpose": "remediation",
                        "expected_duration_sec": 60,
                        "timeout_duration_sec": 300,
                        "retry_count": 0,
                        "retry_delay": 5,
                        "on_failure": "stop",
                    }
                ],
                "workflows": [
                    {
                        "name": "Node service response",
                        "enabled": True,
                        "communications": {"mode": "inherit", "routes": []},
                        "recipe_ingredients": [],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

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
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([action])])

    service = RepoSyncService(db)
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_branch="main",
        git_actions_path="shared",
    )
    service.git_manager = _FakeGitManager(tmp_path)

    with pytest.raises(RepoSyncError):
        await service.export_actions()


@pytest.mark.asyncio
async def test_clear_workflow_actions_deletes_workflows_before_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = SimpleNamespace(id=21, name="Node service response", description="workflow")
    action = SimpleNamespace(id=11, task_key_template="restart_service")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([workflow]), _ScalarResult([action])])

    service = RepoSyncService(db)
    calls: list[str] = []

    async def delete_recipe_mock(*args, **kwargs):
        calls.append("workflow")
        return {"status": "deleted"}

    async def delete_ingredient_mock(*args, **kwargs):
        calls.append("action")
        return {"status": "deleted"}

    monkeypatch.setattr("api.services.repo_sync_service.delete_recipe", delete_recipe_mock)
    monkeypatch.setattr("api.services.repo_sync_service.delete_ingredient", delete_ingredient_mock)

    result = await service.clear_workflow_actions()

    assert result["status"] == "success"
    assert result["cleared"] == {"workflows": 1, "actions": 1}
    assert calls == ["workflow", "action"]


def test_runtime_dependencies_include_gitpython() -> None:
    pyproject = Path("pyproject.toml")
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert any(str(dep).lower().startswith("gitpython") for dep in dependencies)


def test_api_runtime_image_installs_git_binary() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    runtime_section = dockerfile.split("FROM python:3.11-slim AS python-runtime-base", 1)[1]
    install_block = runtime_section.split("RUN useradd", 1)[0]

    assert "git \\" in install_block


def test_git_manager_embeds_github_pat_in_clone_url() -> None:
    manager = GitManager()
    manager.settings = SimpleNamespace(
        git_repo_url="https://github.com/example/config.git",
        git_token="secret-token",
        git_ssh_key_path="",
    )

    assert (
        manager._credentialed_repo_url()
        == "https://x-access-token:secret-token@github.com/example/config.git"
    )


def test_git_manager_embeds_gitlab_pat_in_clone_url() -> None:
    manager = GitManager()
    manager.settings = SimpleNamespace(
        git_repo_url="https://gitlab.com/example/config.git",
        git_token="secret-token",
        git_ssh_key_path="",
    )

    assert (
        manager._credentialed_repo_url()
        == "https://oauth2:secret-token@gitlab.com/example/config.git"
    )


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
    assert paths == ["prometheus/rules/imported/NodeFilesystemAlmostOutOfSpace.yaml"]
    payload = yaml.safe_load(service.git_manager.last_changes[paths[0]])
    assert list(payload["additionalPrometheusRulesMap"]) == ["NodeFilesystemAlmostOutOfSpace"]
    assert (
        payload["additionalPrometheusRulesMap"]["NodeFilesystemAlmostOutOfSpace"]["groups"][0][
            "name"
        ]
        == "node-filesystem"
    )
    assert (
        payload["additionalPrometheusRulesMap"]["NodeFilesystemAlmostOutOfSpace"]["groups"][0][
            "rules"
        ][0]["alert"]
        == "NodeFilesystemAlmostOutOfSpace"
    )


@pytest.mark.asyncio
async def test_import_alert_rules_supports_wrapped_nested_files(tmp_path: Path) -> None:
    alerts_dir = tmp_path / "alerts" / "kubernetes"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "kube-api-down.yaml").write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    "kube-api-down": {
                        "groups": [
                            {
                                "name": "kube-api-down",
                                "rules": [
                                    {"alert": "kube-api-down-warning", "expr": "up == 0"},
                                    {"alert": "kube-api-down-critical", "expr": "up == 0"},
                                ],
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    create_or_update_rule = AsyncMock(return_value={"status": "success"})
    service.crd_manager = SimpleNamespace(create_or_update_rule=create_or_update_rule)

    result = await service.import_alert_rules()

    assert result["status"] == "success"
    assert result["imported"]["alert_rules"] == 2
    assert result["imported"]["files_scanned"] == 1
    assert result["imported"]["files_with_groups"] == 1
    assert result["imported"]["files_skipped"] == 0
    first_call = create_or_update_rule.await_args_list[0]
    assert first_call.args[:4] == (
        "kube-api-down-warning",
        "kube-api-down",
        "kube-api-down",
        {"alert": "kube-api-down-warning", "expr": "up == 0"},
    )
    assert first_call.kwargs["source_metadata"].relative_path == "kubernetes/kube-api-down.yaml"
    assert first_call.kwargs["source_metadata"].source_format == (
        ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP
    )
    assert first_call.kwargs["source_metadata"].wrapper_key == "kube-api-down"


@pytest.mark.asyncio
async def test_import_alert_rules_rejects_unsupported_files(tmp_path: Path) -> None:
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "unsupported.yaml").write_text(
        yaml.safe_dump({"apiVersion": "v1", "kind": "ConfigMap"}, sort_keys=False),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service.crd_manager = SimpleNamespace(create_or_update_rule=AsyncMock())

    with pytest.raises(RepoSyncError):
        await service.import_alert_rules()


@pytest.mark.asyncio
async def test_import_alert_rules_skips_invalid_crd_rules_and_reports_summary(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts" / "kubernetes"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "kube-container-waiting.yaml").write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    "kube-container-waiting": {
                        "groups": [
                            {
                                "name": "kube-container-waiting",
                                "rules": [
                                    {
                                        "alert": "kube-container-waiting-warning",
                                        "expr": 'k8s.container.status.reason{job="otel"} > 0',
                                    },
                                    {
                                        "alert": "kube-container-waiting-critical",
                                        "expr": "up == 0",
                                    },
                                ],
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    async def create_or_update_rule(
        rule_name: str,
        _group_name: str,
        _crd_name: str,
        _rule_data: dict[str, object],
        *,
        source_metadata: object | None = None,
    ) -> dict[str, object]:
        assert source_metadata is not None
        if rule_name == "kube-container-waiting-warning":
            return {
                "status": "error",
                "message": "Failed to create CRD: validation rejected the rule",
                "code": 422,
                "body_message": (
                    'admission webhook "prometheusrulevalidate.monitoring.coreos.com" '
                    "denied the request: Rules are not valid"
                ),
                "body_reason": "Invalid",
            }
        return {"status": "success"}

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service.crd_manager = SimpleNamespace(
        create_or_update_rule=AsyncMock(side_effect=create_or_update_rule)
    )

    result = await service.import_alert_rules()

    assert result["status"] == "success"
    assert result["imported"]["alert_rules"] == 1
    assert result["imported"]["invalid_rules"] == 1
    assert result["imported"]["files_with_invalid_rules"] == 1
    assert "Skipped 1 invalid rule across 1 file." in result["message"]
    assert (
        "kube-container-waiting-warning in kubernetes/kube-container-waiting.yaml"
        in result["message"]
    )


@pytest.mark.asyncio
async def test_import_alert_rules_succeeds_when_all_supported_rules_are_invalid(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "kube-container-waiting.yaml").write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    "kube-container-waiting": {
                        "groups": [
                            {
                                "name": "kube-container-waiting",
                                "rules": [
                                    {
                                        "alert": "kube-container-waiting-warning",
                                        "expr": 'k8s.container.status.reason{job="otel"} > 0',
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service.crd_manager = SimpleNamespace(
        create_or_update_rule=AsyncMock(
            return_value={
                "status": "error",
                "message": "Failed to create CRD: invalid rule",
                "code": 422,
                "body_message": "Rules are not valid",
                "body_reason": "Invalid",
            }
        )
    )

    result = await service.import_alert_rules()

    assert result["status"] == "success"
    assert result["imported"]["alert_rules"] == 0
    assert result["imported"]["invalid_rules"] == 1
    assert result["imported"]["files_with_invalid_rules"] == 1
    assert result["message"].startswith("Imported 0 alert rules from Git.")


@pytest.mark.asyncio
async def test_export_alert_rules_preserves_wrapped_repo_paths_and_deletes_obsolete_files(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts" / "kubernetes"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "kube-api-down.yaml").write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    "kube-api-down": {
                        "groups": [
                            {
                                "name": "kube-api-down",
                                "rules": [{"alert": "kube-api-down-warning", "expr": "up == 0"}],
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    obsolete_path = tmp_path / "alerts" / "obsolete.yaml"
    obsolete_path.write_text(
        yaml.safe_dump(
            {
                "groups": [
                    {
                        "name": "obsolete",
                        "rules": [{"alert": "obsolete-warning", "expr": "up == 0"}],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_file_per_alert=True,
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(
        return_value=[
            {
                "group": "kube-api-down",
                "crd": "kube-api-down",
                "file": "kubernetes/kube-api-down.yaml",
                "source_format": ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
                "wrapper_key": "kube-api-down",
                "rule": {"alert": "kube-api-down-warning", "expr": "up == 1"},
            },
            {
                "group": "fresh-alert",
                "crd": "fresh-alert",
                "file": "kubernetes/fresh-alert.yaml",
                "rule": {"alert": "fresh-alert-warning", "expr": "up == 2"},
            },
        ]
    )

    result = await service.export_alert_rules()

    assert result["status"] == "success"
    assert result["exported"]["alert_rules"] == 2
    assert result["exported"]["files_written"] == 3
    assert service.git_manager.last_changes is not None
    assert "alerts/kubernetes/kube-api-down.yaml" in service.git_manager.last_changes
    assert "alerts/imported/fresh-alert-warning.yaml" in service.git_manager.last_changes
    assert "alerts/obsolete.yaml" in service.git_manager.last_changes
    assert service.git_manager.last_changes["alerts/obsolete.yaml"] is None
    assert "alerts/kube-api-down.yaml" not in service.git_manager.last_changes

    existing_payload = yaml.safe_load(
        service.git_manager.last_changes["alerts/kubernetes/kube-api-down.yaml"]
    )
    assert list(existing_payload["additionalPrometheusRulesMap"]) == ["kube-api-down"]
    assert (
        existing_payload["additionalPrometheusRulesMap"]["kube-api-down"]["groups"][0]["rules"][0][
            "expr"
        ]
        == "up == 1"
    )

    new_payload = yaml.safe_load(
        service.git_manager.last_changes["alerts/imported/fresh-alert-warning.yaml"]
    )
    assert list(new_payload["additionalPrometheusRulesMap"]) == ["fresh-alert-warning"]
    assert (
        new_payload["additionalPrometheusRulesMap"]["fresh-alert-warning"]["groups"][0]["rules"][0][
            "alert"
        ]
        == "fresh-alert-warning"
    )


@pytest.mark.asyncio
async def test_export_alert_rules_noop_does_not_commit_or_rewrite(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts" / "kubernetes"
    alerts_dir.mkdir(parents=True)
    original_text = yaml.safe_dump(
        {
            "additionalPrometheusRulesMap": {
                "kube-api-down": {
                    "groups": [
                        {
                            "name": "kube-api-down",
                            "rules": [
                                {
                                    "alert": "kube-api-down-warning",
                                    "expr": "up == 0",
                                    "labels": {"severity": "warning"},
                                }
                            ],
                        }
                    ]
                }
            }
        },
        sort_keys=False,
    )
    (alerts_dir / "kube-api-down.yaml").write_text(original_text, encoding="utf-8")

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_file_per_alert=True,
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(
        return_value=[
            {
                "group": "kube-api-down",
                "crd": "kube-api-down",
                "file": "kubernetes/kube-api-down.yaml",
                "source_format": ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
                "wrapper_key": "kube-api-down",
                "rule": {
                    "alert": "kube-api-down-warning",
                    "expr": "up == 0",
                    "labels": {"severity": "warning"},
                },
            },
        ]
    )

    result = await service.export_alert_rules()

    assert result["status"] == "success"
    assert result["message"] == "Alert rules are already in sync with Git."
    assert result["exported"]["files_written"] == 0
    assert result["details"]["change_count"] == 0
    assert service.git_manager.last_changes is None
    assert (alerts_dir / "kube-api-down.yaml").read_text(encoding="utf-8") == original_text


@pytest.mark.asyncio
async def test_export_alert_rules_scans_repo_when_annotation_is_stale(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts" / "kubernetes"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "kube-api-down.yaml").write_text(
        yaml.safe_dump(
            {
                "additionalPrometheusRulesMap": {
                    "kube-api-down": {
                        "groups": [
                            {
                                "name": "kube-api-down",
                                "rules": [{"alert": "kube-api-down-warning", "expr": "up == 0"}],
                            }
                        ]
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_file_per_alert=True,
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(
        return_value=[
            {
                "group": "kube-api-down",
                "crd": "kube-api-down",
                "file": "stale/missing.yaml",
                "source_format": ALERT_RULE_SOURCE_FORMAT_ADDITIONAL_MAP,
                "wrapper_key": "missing",
                "rule": {"alert": "kube-api-down-warning", "expr": "up == 1"},
            },
        ]
    )

    result = await service.export_alert_rules()

    assert result["status"] == "success"
    assert service.git_manager.last_changes is not None
    assert sorted(service.git_manager.last_changes) == ["alerts/kubernetes/kube-api-down.yaml"]
    payload = yaml.safe_load(
        service.git_manager.last_changes["alerts/kubernetes/kube-api-down.yaml"]
    )
    assert (
        payload["additionalPrometheusRulesMap"]["kube-api-down"]["groups"][0]["rules"][0]["expr"]
        == "up == 1"
    )


@pytest.mark.asyncio
async def test_export_alert_rules_preview_does_not_commit(
    tmp_path: Path,
) -> None:
    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_unmapped_rules_path="new",
        git_file_per_alert=True,
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(
        return_value=[
            {
                "group": "fresh-alert",
                "crd": "fresh-alert",
                "file": "",
                "rule": {"alert": "fresh-alert-warning", "expr": "up == 2"},
            },
        ]
    )

    result = await service.export_alert_rules_preview()

    assert result["status"] == "success"
    assert result["exported"]["files_added"] == 1
    assert result["details"]["added_files"] == ["alerts/new/fresh-alert-warning.yaml"]
    assert service.git_manager.last_changes is None


@pytest.mark.asyncio
async def test_export_alert_rules_preserves_recording_rules_when_alerts_are_removed(
    tmp_path: Path,
) -> None:
    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir(parents=True)
    (alerts_dir / "mixed.yaml").write_text(
        yaml.safe_dump(
            {
                "groups": [
                    {
                        "name": "mixed",
                        "rules": [
                            {"alert": "ObsoleteAlert", "expr": "up == 0"},
                            {"record": "job:up:sum", "expr": "sum(up)"},
                        ],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    service = RepoSyncService()
    service.settings = SimpleNamespace(
        git_enabled=True,
        git_repo_url="https://github.com/example/config.git",
        git_rules_path="alerts",
        git_file_per_alert=True,
        prometheus_use_crds=True,
    )
    service.git_manager = _FakeGitManager(tmp_path)
    service._current_alert_rules = AsyncMock(return_value=[])

    result = await service.export_alert_rules()

    assert result["status"] == "success"
    assert result["exported"]["files_changed"] == 1
    assert result["exported"]["files_deleted"] == 0
    assert service.git_manager.last_changes is not None
    assert service.git_manager.last_changes["alerts/mixed.yaml"] is not None
    payload = yaml.safe_load(service.git_manager.last_changes["alerts/mixed.yaml"])
    rules = payload["groups"][0]["rules"]
    assert rules == [{"record": "job:up:sum", "expr": "sum(up)"}]


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

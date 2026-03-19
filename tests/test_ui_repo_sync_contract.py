from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "ui" / "src" / "App.tsx"


def test_alert_rules_page_exposes_repo_sync_controls() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "AlertRuleRepoSyncPanel" in content
    assert "Clear alert rules" in content
    assert 'Type "yes" to continue.' in content
    assert "Only admins can clear live alert rules." in content
    assert '"/api/v1/repo-sync/alert-rules/import"' in content
    assert '"/api/v1/repo-sync/alert-rules/export"' in content


def test_workflow_and_action_pages_expose_shared_repo_sync_controls() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "WorkflowActionRepoSyncPanel" in content
    assert "DangerConfirmButton" in content
    assert "Clear workflows and actions" in content
    assert "Only admins can clear workflows and actions." in content
    assert '"/api/v1/repo-sync/workflow-actions/import"' in content
    assert '"/api/v1/repo-sync/workflow-actions/export"' in content
    assert "settings.git_workflows_path" in content
    assert "settings.git_actions_path" in content

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "ui" / "src" / "App.tsx"


def _section(content: str, start_marker: str, end_marker: str) -> str:
    return content.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_alert_rules_page_exposes_repo_sync_controls() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "AlertRuleRepoSyncPanel" in content
    assert "Clear alert rules" in content
    assert 'Type "yes" to continue.' in content
    assert "Only admins can clear live alert rules." in content
    assert '"/api/v1/repo-sync/alert-rules/import"' in content
    assert '"/api/v1/repo-sync/alert-rules/export"' in content
    assert '"/api/v1/repo-sync/alert-rules/export-preview"' in content


def test_workflows_page_uses_combined_repo_sync_modal_flow() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    workflows_page = _section(content, "function WorkflowsPage()", "function ActionsPage()")
    assert "WorkflowRepoSyncPanel" in workflows_page
    assert "HelpRail" not in workflows_page
    assert '"/api/v1/repo-sync/workflow-actions/import"' in workflows_page
    assert '"/api/v1/repo-sync/workflow-actions/export"' in workflows_page
    assert '"/api/v1/repo-sync/workflows/import"' not in workflows_page
    assert '"/api/v1/repo-sync/workflows/export"' not in workflows_page
    assert "Create workflow" in workflows_page
    assert "dialog-card dialog-card-wide" in workflows_page
    assert "workflows loaded." in workflows_page
    assert "Clear workflows and actions" in content
    assert "workflow-row-disabled" in workflows_page


def test_actions_page_uses_modal_flow_without_repo_sync() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    actions_page = _section(content, "function ActionsPage()", "function AccessPage()")
    assert "HelpRail" not in actions_page
    assert "ActionRepoSyncPanel" not in content
    assert '"/api/v1/repo-sync/actions/import"' not in actions_page
    assert '"/api/v1/repo-sync/actions/export"' not in actions_page
    assert '"/api/v1/repo-sync/workflow-actions/import"' not in actions_page
    assert '"/api/v1/repo-sync/workflow-actions/export"' not in actions_page
    assert "Create action" in actions_page
    assert "dialog-card dialog-card-wide" in actions_page
    assert "actions loaded." in actions_page
    assert "Clear workflows and actions" not in actions_page

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "ui" / "src" / "App.tsx"


def test_alert_rule_editor_uses_repo_relative_path_language() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "Repo path / CRD" in content
    assert "Use a repo-relative alert-rule path such as kubernetes/kube-api-down.yaml." in content
    assert 'placeholder={settings.git_enabled ? "kubernetes/kube-api-down.yaml"' in content


def test_alert_rule_editor_treats_identity_changes_as_create_new() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert 'const editingRuleSource = editingRule?.file || editingRule?.crd || "";' in content
    assert "const createInsteadOfUpdate =" in content
    assert "values.name !== editingRule.name" in content
    assert "values.group !== editingRule.group" in content
    assert "values.file !== editingRuleSource" in content
    assert "Changing the rule name, group, or source path creates a new rule." in content


def test_alert_rule_page_forces_refetch_after_repo_sync_mutations() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "const refreshRules = async () => {" in content
    assert 'await queryClient.invalidateQueries({ queryKey: ["prometheus-rules"] });' in content
    assert (
        'await queryClient.refetchQueries({ queryKey: ["prometheus-rules"], exact: true, type: "active" });'
        in content
    )
    assert "await refreshRules();" in content

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


def test_alert_rule_page_uses_modal_create_and_edit_flow() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "const [editorOpen, setEditorOpen] = useState(false);" in content
    assert "const openCreateRuleDialog = () => {" in content
    assert "const openEditRuleDialog = (rule: PrometheusRule) => {" in content
    assert "const closeRuleDialog = () => {" in content
    assert "onClick={openCreateRuleDialog}" in content
    assert "onClick={() => openEditRuleDialog(rule)}" in content
    assert 'className="dialog-card dialog-card-wide"' in content


def test_alert_rule_page_forces_refetch_after_repo_sync_mutations() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "const refreshRules = async () => {" in content
    assert 'await queryClient.invalidateQueries({ queryKey: ["prometheus-rules"] });' in content
    assert (
        'await queryClient.refetchQueries({ queryKey: ["prometheus-rules"], exact: true, type: "active" });'
        in content
    )
    assert "await refreshRules();" in content


def test_alert_rule_page_recovers_from_gateway_timeout_imports() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "function isGatewayTimeoutError(error: unknown): boolean {" in content
    assert (
        "Import request timed out at the gateway. Refreshing alert inventory in the background."
        in content
    )
    assert (
        "const recoverRulesAfterGatewayTimeout = async (baselineRuleCount: number) => {" in content
    )
    assert (
        'notify("success", `Alert inventory refreshed. ${refreshedRules} rules loaded.`);'
        in content
    )


def test_alert_rule_page_hides_unreliable_runtime_state_in_crd_mode() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "const showRuntimeStatus = !settings.prometheus_use_crds;" in content
    assert (
        'className={`status-grid ${showRuntimeStatus ? "" : "status-grid-single"}`.trim()}'
        in content
    )
    assert 'title="Rules loaded"' in content
    assert "{showRuntimeStatus ? <th>Status</th> : null}" in content
    assert "{showRuntimeStatus ? (" in content
    assert "CRD-backed rules do not expose live runtime state on this page." not in content


def test_alert_rule_page_removes_help_rail_and_keeps_inventory_count() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "Alert-rule help" not in content
    assert (
        "subtitle={`Source: ${rulesQuery.data.source}. ${totalRuleCount} rules loaded." in content
    )

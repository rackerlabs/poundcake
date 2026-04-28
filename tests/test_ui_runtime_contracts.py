from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_TS = REPO_ROOT / "ui" / "src" / "api.ts"
APP_TSX = REPO_ROOT / "ui" / "src" / "App.tsx"
CONTRACTS_TS = REPO_ROOT / "ui" / "src" / "contracts.ts"


def test_ui_api_fetch_parses_with_runtime_schema() -> None:
    content = API_TS.read_text(encoding="utf-8")
    assert "return schema.parse(body);" in content


def test_ui_app_uses_runtime_contract_schemas_for_key_flows() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert 'apiGet("/api/v1/settings", appSettingsSchema)' in content
    assert 'apiGet("/api/v1/prometheus/rules", prometheusRuleListResponseSchema)' in content
    assert "suppressionCreateRequestSchema.parse({" in content
    assert "recipeCreateRequestSchema.parse(payload)" in content
    assert "ingredientCreateRequestSchema.parse(payload)" in content
    assert "authRoleBindingCreateRequestSchema.parse(payload)" in content


def test_overview_page_polls_for_fresh_dashboard_data() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert 'queryKey: ["overview-dashboard"]' in content
    assert "refetchInterval: 15_000" in content
    assert "refetchIntervalInBackground: false" in content
    assert "refetchOnWindowFocus: true" in content


def test_incident_drilldown_surfaces_alert_context_for_waiting_clear_triage() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "Alert details" in content
    assert "incidentPrimaryResource" in content
    assert "incidentScopeFields" in content
    assert "horizontalpodautoscaler" in content
    assert "generatorURL" in content
    assert "waiting_clear" in content
    assert "waiting_ticket_close" in content


def test_suppression_form_supports_multiple_matchers() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert 'name: "matchers"' in content
    assert "matcherFields.append(emptySuppressionMatcher())" in content
    assert "matcherFields.fields.map" in content
    assert "matchers.${index}.label_key" in content
    assert "matchers.${index}.operator" in content
    assert "matchers.${index}.value" in content
    assert "values.matchers.map((matcher)" in content


def test_suppression_form_supports_until_canceled_windows() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    css = (REPO_ROOT / "ui" / "src" / "app.css").read_text(encoding="utf-8")
    assert 'ends_mode: z.enum(["at_time", "until_canceled"])' in content
    assert 'PERMANENT_SUPPRESSION_ENDS_AT = "9999-12-31T23:59:59Z"' in content
    assert "datetimeLocalToUtcIso(values.starts_at)" in content
    assert 'datetimeLocalToUtcIso(values.ends_at || "")' in content
    assert "suppression-schedule-grid" in content
    assert "suppression-window-row" in content
    assert "suppression-window-actions" in content
    assert 'return status === "active" || status === "scheduled";' in content
    assert "showCancelAction" in content
    assert "Until canceled" in content
    assert "formatSuppressionEndsAt(item.ends_at)" in content
    assert 'input[type="checkbox"]' in css
    assert ".suppression-schedule-grid" in css
    assert ".suppression-window-row" in css
    assert ".suppression-window-actions" in css
    assert ".checkbox-card" in css


def test_ui_contract_objects_are_strict() -> None:
    content = CONTRACTS_TS.read_text(encoding="utf-8")
    assert (
        "const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict();"
        in content
    )
    assert "export const appSettingsSchema = strictObject({" in content
    assert "export const orderResponseSchema = strictObject({" in content
    assert "fingerprint_when_active: z.string().nullable().optional()," in content
    assert "result: z.unknown().nullable().optional()," in content
    assert "file: z.string().nullable().optional()," in content
    assert "crd: z.string().nullable().optional()," in content
    assert "namespace: z.string().nullable().optional()," in content
    assert "export const recipeCreateRequestSchema = strictObject({" in content

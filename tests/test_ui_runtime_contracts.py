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

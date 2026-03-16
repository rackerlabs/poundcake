from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import pytest
from click.testing import CliRunner

from cli.main import cli
from cli.session import SessionStore

Handler = Callable[[dict[str, Any]], httpx.Response]


class FakeAPI:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Handler] = {}
        self.requests: list[dict[str, Any]] = []

    def add_json(
        self,
        method: str,
        path: str,
        payload: Any,
        *,
        status_code: int = 200,
    ) -> None:
        def handler(request: dict[str, Any]) -> httpx.Response:
            return httpx.Response(
                status_code,
                json=payload,
                request=httpx.Request(request["method"], request["url"]),
            )

        self.routes[(method.upper(), path)] = handler

    def add_handler(self, method: str, path: str, handler: Handler) -> None:
        self.routes[(method.upper(), path)] = handler

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        cookies: dict[str, Any] | None = None,
        timeout: float | None = None,
        **_: Any,
    ) -> httpx.Response:
        request = {
            "method": method.upper(),
            "url": url,
            "path": urlparse(url).path,
            "headers": headers or {},
            "json": json,
            "params": params or {},
            "cookies": cookies,
            "timeout": timeout,
        }
        self.requests.append(request)
        handler = self.routes[(request["method"], request["path"])]
        return handler(request)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _session_file(config_home: Path) -> Path:
    return config_home / "poundcake" / "session.json"


def _write_session(config_home: Path, base_url: str, payload: dict[str, Any]) -> None:
    store = SessionStore(path=_session_file(config_home))
    _session_file(config_home).parent.mkdir(parents=True, exist_ok=True)
    data = {base_url: payload}
    _session_file(config_home).write_text(json.dumps(data), encoding="utf-8")
    return store


def test_cli_is_packaged_as_console_application() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]
    include = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    dependencies = pyproject["project"]["dependencies"]

    assert scripts["poundcake"] == "cli.main:main"
    assert scripts["poundcake-cli"] == "cli.main:main"
    assert "cli*" in include
    assert any(dependency.startswith("click") for dependency in dependencies)


def test_auth_login_persists_session_and_logout_clears_it(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/auth/providers",
        [
            {
                "name": "local",
                "label": "Local Superuser",
                "login_mode": "password",
                "cli_login_mode": "password",
                "browser_login": False,
                "device_login": False,
                "password_login": True,
            }
        ],
    )
    fake_api.add_json(
        "POST",
        "/api/v1/auth/login",
        {
            "session_id": "session-123",
            "username": "alice",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "provider": "local",
            "role": "admin",
            "display_name": "Alice",
            "is_superuser": True,
            "permissions": ["read", "manage_access", "superuser"],
            "token_type": "Bearer",
        },
    )
    fake_api.add_json("POST", "/api/v1/auth/logout", {"message": "Logged out successfully"})
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    login_result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "auth",
            "login",
            "--username",
            "alice",
            "--password",
            "secret",
        ],
    )
    assert login_result.exit_code == 0, login_result.output

    session_path = _session_file(tmp_path)
    assert session_path.exists()
    assert oct(session_path.stat().st_mode & 0o777) == "0o600"
    saved = json.loads(session_path.read_text(encoding="utf-8"))
    assert saved["http://example.test"]["session_id"] == "session-123"
    assert saved["http://example.test"]["provider"] == "local"
    assert saved["http://example.test"]["role"] == "admin"
    assert fake_api.requests[0]["cookies"] is None
    assert fake_api.requests[1]["json"] == {
        "provider": "local",
        "username": "alice",
        "password": "secret",
    }

    logout_result = runner.invoke(
        cli,
        ["--url", "http://example.test", "auth", "logout"],
    )
    assert logout_result.exit_code == 0, logout_result.output
    saved_after = json.loads(session_path.read_text(encoding="utf-8"))
    assert "http://example.test" not in saved_after
    assert fake_api.requests[2]["cookies"] == {"session_token": "session-123"}


def test_api_key_takes_precedence_over_stored_session(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json("GET", "/api/v1/orders", [])
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _write_session(
        tmp_path,
        "http://example.test",
        {
            "session_id": "session-123",
            "username": "alice",
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    )

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--api-key",
            "internal-key",
            "--format",
            "json",
            "incidents",
            "list",
        ],
    )
    assert result.exit_code == 0, result.output
    request = fake_api.requests[0]
    assert request["headers"]["Authorization"] == "Bearer internal-key"
    assert request["cookies"] is None


def test_auth0_device_login_persists_session(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/auth/providers",
        [
            {
                "name": "auth0",
                "label": "Auth0",
                "login_mode": "oidc",
                "cli_login_mode": "device",
                "browser_login": True,
                "device_login": True,
                "password_login": False,
            }
        ],
    )
    fake_api.add_json(
        "POST",
        "/api/v1/auth/device/start",
        {
            "provider": "auth0",
            "device_code": "device-123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://example.auth0.test/activate",
            "verification_uri_complete": "https://example.auth0.test/activate?user_code=ABCD-EFGH",
            "expires_in": 600,
            "interval": 1,
        },
    )
    fake_api.add_json(
        "POST",
        "/api/v1/auth/device/poll",
        {
            "status": "authorized",
            "session": {
                "session_id": "session-device",
                "username": "alice@example.com",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "provider": "auth0",
                "role": "operator",
                "display_name": "Alice Example",
                "is_superuser": False,
                "permissions": ["read", "manage_recipes"],
                "token_type": "Bearer",
            },
        },
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setattr("cli.commands.auth.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "auth",
            "login",
            "--provider",
            "auth0",
        ],
    )
    assert result.exit_code == 0, result.output
    saved = json.loads(_session_file(tmp_path).read_text(encoding="utf-8"))
    assert saved["http://example.test"]["session_id"] == "session-device"
    assert saved["http://example.test"]["provider"] == "auth0"
    assert fake_api.requests[2]["json"] == {"provider": "auth0", "device_code": "device-123"}


def test_auth_bindings_create_maps_payload(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "POST",
        "/api/v1/auth/bindings",
        {
            "id": 17,
            "provider": "auth0",
            "binding_type": "group",
            "role": "operator",
            "principal_id": None,
            "external_group": "monitoring-operators",
            "created_by": "alice",
            "created_at": "2099-01-01T00:00:00+00:00",
            "updated_at": "2099-01-01T00:00:00+00:00",
            "principal": None,
        },
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _write_session(
        tmp_path,
        "http://example.test",
        {
            "session_id": "session-123",
            "username": "alice",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "provider": "auth0",
            "role": "admin",
        },
    )

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "auth",
            "bindings",
            "create",
            "--provider",
            "auth0",
            "--type",
            "group",
            "--role",
            "operator",
            "--group",
            "monitoring-operators",
        ],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.requests[0]["json"] == {
        "provider": "auth0",
        "binding_type": "group",
        "role": "operator",
        "external_group": "monitoring-operators",
        "principal_id": None,
    }
    assert fake_api.requests[0]["cookies"] == {"session_token": "session-123"}


def test_expired_session_is_removed_before_request(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json("GET", "/api/v1/orders", [])
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _write_session(
        tmp_path,
        "http://example.test",
        {
            "session_id": "session-expired",
            "username": "alice",
            "expires_at": "2000-01-01T00:00:00+00:00",
        },
    )

    result = runner.invoke(
        cli,
        ["--url", "http://example.test", "--format", "json", "incidents", "list"],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.requests[0]["cookies"] is None
    saved = json.loads(_session_file(tmp_path).read_text(encoding="utf-8"))
    assert "http://example.test" not in saved


def test_overview_aggregates_existing_endpoints_in_table_mode(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json("GET", "/api/v1/health", {"status": "healthy", "version": "2.0.135"})
    fake_api.add_json(
        "GET",
        "/api/v1/stats",
        {"total_alerts": 5, "recent_alerts": 2, "total_recipes": 3, "total_executions": 9},
    )
    fake_api.add_json(
        "GET",
        "/api/v1/observability/overview",
        {"failures": {"orders_failed": 1, "dishes_failed": 2}, "suppressions": {"active": 1}},
    )
    fake_api.add_json(
        "GET",
        "/api/v1/observability/activity",
        [{"type": "incident", "title": "Disk Full", "status": "processing", "target_id": "7"}],
    )
    fake_api.add_json(
        "GET",
        "/api/v1/orders",
        [
            {
                "id": 7,
                "alert_group_name": "Disk Full",
                "processing_status": "processing",
                "alert_status": "firing",
                "severity": "critical",
                "communications": [],
            }
        ],
    )
    fake_api.add_json(
        "GET",
        "/api/v1/communications/activity",
        [
            {
                "communication_id": "comm-1",
                "reference_name": "Disk Full",
                "channel": "rackspace_core",
                "lifecycle_state": "open",
                "destination": "rackspace_core",
            }
        ],
    )
    fake_api.add_json(
        "GET",
        "/api/v1/suppressions",
        [
            {
                "id": 9,
                "name": "Maintenance",
                "status": "scheduled",
                "ends_at": "2099-01-01T01:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(cli, ["--url", "http://example.test", "overview"])
    assert result.exit_code == 0, result.output
    assert "Summary" in result.output
    assert "Recent Incidents" in result.output
    assert "Disk Full" in result.output
    requested_paths = {request["path"] for request in fake_api.requests}
    assert requested_paths == {
        "/api/v1/health",
        "/api/v1/stats",
        "/api/v1/observability/overview",
        "/api/v1/observability/activity",
        "/api/v1/orders",
        "/api/v1/communications/activity",
        "/api/v1/suppressions",
    }


def test_actions_create_uses_template_presets(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()

    def create_handler(request: dict[str, Any]) -> httpx.Response:
        body = dict(request["json"] or {})
        body.update(
            {
                "id": 11,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "deleted": False,
                "deleted_at": None,
            }
        )
        return httpx.Response(
            200, json=body, request=httpx.Request(request["method"], request["url"])
        )

    fake_api.add_handler("POST", "/api/v1/ingredients/", create_handler)
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "actions",
            "create",
            "--template",
            "remediation",
            "--task-key-template",
            "pvc.expand",
            "--execution-target",
            "k8s.patch",
            "--expected-duration-sec",
            "60",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = fake_api.requests[0]["json"]
    assert payload["execution_engine"] == "stackstorm"
    assert payload["execution_purpose"] == "remediation"
    assert payload["execution_target"] == "k8s.patch"


def test_legacy_alias_matches_canonical_actions_output(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/ingredients/",
        [
            {
                "id": 1,
                "task_key_template": "demo.action",
                "execution_target": "stackstorm",
                "destination_target": "",
                "execution_engine": "stackstorm",
                "execution_purpose": "remediation",
                "is_blocking": True,
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    canonical = runner.invoke(
        cli, ["--url", "http://example.test", "--format", "json", "actions", "list"]
    )
    alias = runner.invoke(
        cli, ["--url", "http://example.test", "--format", "json", "ingredients", "list"]
    )
    assert canonical.exit_code == 0, canonical.output
    assert alias.exit_code == 0, alias.output
    assert canonical.output == alias.output


def test_workflows_create_builds_local_comms_payload(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/ingredients/42",
        {
            "id": 42,
            "execution_engine": "stackstorm",
            "execution_purpose": "remediation",
        },
    )

    def create_handler(request: dict[str, Any]) -> httpx.Response:
        body = dict(request["json"] or {})
        body.update(
            {
                "id": 12,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "deleted": False,
                "deleted_at": None,
                "communications": body["communications"],
            }
        )
        return httpx.Response(
            200, json=body, request=httpx.Request(request["method"], request["url"])
        )

    fake_api.add_handler("POST", "/api/v1/recipes/", create_handler)
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "workflows",
            "create",
            "--name",
            "Filesystem",
            "--step-json",
            '{"ingredient_id":42,"run_phase":"firing"}',
            "--route-json",
            '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"1781738"}}',
        ],
    )
    assert result.exit_code == 0, result.output
    payload = fake_api.requests[1]["json"]
    assert payload["communications"]["mode"] == "local"
    assert payload["communications"]["routes"][0]["position"] == 1
    assert payload["recipe_ingredients"][0]["step_order"] == 1


def test_workflows_reject_managed_communication_actions(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/ingredients/99",
        {
            "id": 99,
            "execution_engine": "bakery",
            "execution_purpose": "comms",
        },
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "workflows",
            "create",
            "--name",
            "Bad Workflow",
            "--step-json",
            '{"ingredient_id":99}',
        ],
    )
    assert result.exit_code != 0
    assert "managed communication action" in result.output
    assert len(fake_api.requests) == 1


def test_global_communications_set_uses_existing_policy_endpoint(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()

    def put_handler(request: dict[str, Any]) -> httpx.Response:
        body = dict(request["json"] or {})
        body.update({"configured": True, "lifecycle_summary": {"open": "open on escalation"}})
        return httpx.Response(
            200, json=body, request=httpx.Request(request["method"], request["url"])
        )

    fake_api.add_handler("PUT", "/api/v1/communications/policy", put_handler)
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "global-communications",
            "set",
            "--route-json",
            '{"label":"Core","execution_target":"rackspace_core"}',
            "--route-json",
            '{"label":"Discord","execution_target":"discord","destination_target":"ops-alerts"}',
        ],
    )
    assert result.exit_code == 0, result.output
    payload = fake_api.requests[0]["json"]
    assert payload["routes"][0]["position"] == 1
    assert payload["routes"][1]["position"] == 2


def test_alert_rules_create_merges_json_fields(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json("POST", "/api/v1/prometheus/rules", {"status": "ok"})
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "alert-rules",
            "create",
            "rules-file",
            "node",
            "DiskFull",
            "--expr",
            "up == 0",
            "--labels-json",
            '{"team":"platform"}',
            "--annotations-json",
            '{"runbook":"https://example.test/runbook"}',
            "--severity",
            "critical",
            "--summary",
            "Disk full",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = fake_api.requests[0]["json"]
    assert payload["labels"] == {"team": "platform", "severity": "critical"}
    assert payload["annotations"] == {
        "runbook": "https://example.test/runbook",
        "summary": "Disk full",
    }


def test_suppressions_create_sends_matcher_payload(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()

    def create_handler(request: dict[str, Any]) -> httpx.Response:
        body = dict(request["json"] or {})
        body.update(
            {
                "id": 13,
                "status": "scheduled",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "canceled_at": None,
            }
        )
        return httpx.Response(
            201, json=body, request=httpx.Request(request["method"], request["url"])
        )

    fake_api.add_handler("POST", "/api/v1/suppressions", create_handler)
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)
    monkeypatch.setattr("cli.commands.suppressions.getpass.getuser", lambda: "cli-user")

    result = runner.invoke(
        cli,
        [
            "--url",
            "http://example.test",
            "--format",
            "json",
            "suppressions",
            "create",
            "--name",
            "Maintenance",
            "--starts-at",
            "2099-01-01T00:00:00+00:00",
            "--ends-at",
            "2099-01-01T01:00:00+00:00",
            "--matcher-key",
            "alertname",
            "--matcher-value",
            "DiskFull",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = fake_api.requests[0]["json"]
    assert payload["created_by"] == "cli-user"
    assert payload["matchers"] == [
        {"label_key": "alertname", "operator": "eq", "value": "DiskFull"}
    ]


def test_incidents_get_renders_detail_sections(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/orders/7",
        {
            "id": 7,
            "alert_group_name": "Disk Full",
            "processing_status": "processing",
            "alert_status": "firing",
            "severity": "critical",
            "instance": "node-1",
            "req_id": "req-1",
            "counter": 1,
            "remediation_outcome": "pending",
            "auto_close_eligible": False,
            "starts_at": "2026-01-01T00:00:00+00:00",
            "ends_at": None,
            "updated_at": "2026-01-01T00:05:00+00:00",
            "communications": [
                {
                    "id": 1,
                    "execution_target": "rackspace_core",
                    "destination_target": "",
                    "bakery_ticket_id": "T-1",
                    "bakery_operation_id": "op-1",
                    "lifecycle_state": "open",
                    "writable": True,
                    "reopenable": False,
                }
            ],
        },
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(cli, ["--url", "http://example.test", "incidents", "get", "7"])
    assert result.exit_code == 0, result.output
    assert "Incident" in result.output
    assert "Communications" in result.output
    assert "Disk Full" in result.output


def test_communications_get_scans_activity_endpoint(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/communications/activity",
        [
            {
                "communication_id": "comm-1",
                "reference_type": "incident",
                "reference_id": "7",
                "reference_name": "Disk Full",
                "channel": "rackspace_core",
                "destination": "rackspace_core",
                "ticket_id": "T-1",
                "operation_id": "op-1",
                "lifecycle_state": "open",
                "remote_state": "open",
                "writable": True,
                "reopenable": False,
                "updated_at": "2026-01-01T00:05:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(cli, ["--url", "http://example.test", "communications", "get", "comm-1"])
    assert result.exit_code == 0, result.output
    assert "Communication" in result.output
    assert "Disk Full" in result.output
    assert fake_api.requests[0]["params"]["limit"] == 1000


def test_activity_get_scans_dishes_endpoint(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/dishes",
        [
            {
                "id": 5,
                "recipe_id": 2,
                "recipe": {"name": "Filesystem"},
                "order_id": 7,
                "run_phase": "firing",
                "processing_status": "processing",
                "execution_status": "running",
                "execution_ref": "st2-1",
                "retry_attempt": 0,
                "expected_duration_sec": 60,
                "actual_duration_sec": None,
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
                "updated_at": "2026-01-01T00:05:00+00:00",
                "error_message": None,
            }
        ],
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(cli, ["--url", "http://example.test", "activity", "get", "5"])
    assert result.exit_code == 0, result.output
    assert "Workflow Run" in result.output
    assert "Filesystem" in result.output
    assert fake_api.requests[0]["params"]["limit"] == 1000


def test_suppressions_get_renders_summary_when_present(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api = FakeAPI()
    fake_api.add_json(
        "GET",
        "/api/v1/suppressions/13",
        {
            "id": 13,
            "name": "Maintenance",
            "status": "active",
            "scope": "matchers",
            "enabled": True,
            "starts_at": "2026-01-01T00:00:00+00:00",
            "ends_at": "2026-01-01T01:00:00+00:00",
            "reason": "Patch window",
            "created_by": "cli-user",
            "summary_ticket_enabled": True,
            "matchers": [{"label_key": "alertname", "operator": "eq", "value": "DiskFull"}],
            "counters": {
                "suppression_id": 13,
                "total_suppressed": 4,
                "by_alertname": {"DiskFull": 4},
                "by_severity": {"critical": 4},
            },
            "summary": {"state": "open", "total_suppressed": 4},
        },
    )
    monkeypatch.setattr("cli.client.request_with_retry_sync", fake_api)

    result = runner.invoke(cli, ["--url", "http://example.test", "suppressions", "get", "13"])
    assert result.exit_code == 0, result.output
    assert "Suppression" in result.output
    assert "Counters" in result.output
    assert "Summary" in result.output

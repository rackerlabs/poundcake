#!/usr/bin/env python3
"""Interactive CLI for functional testing PoundCake API endpoints."""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


@dataclass(frozen=True)
class Endpoint:
    label: str
    method: str
    path: str
    body_template: dict[str, Any] | list[Any] | None = None
    default_query: dict[str, Any] | None = None


GROUPS: dict[str, list[Endpoint]] = {
    "Auth": [
        Endpoint(
            "Login",
            "POST",
            "/api/v1/auth/login",
            body_template={"username": "admin", "password": "change-me"},
        ),
        Endpoint("Logout", "POST", "/api/v1/auth/logout"),
    ],
    "System": [
        Endpoint("Root", "GET", "/"),
        Endpoint("Metrics", "GET", "/metrics"),
        Endpoint("Health", "GET", "/api/v1/health"),
        Endpoint("Stats", "GET", "/api/v1/stats"),
        Endpoint("Settings", "GET", "/api/v1/settings"),
    ],
    "Orders": [
        Endpoint("List orders", "GET", "/api/v1/orders", default_query={"limit": 50, "offset": 0}),
        Endpoint(
            "Create order",
            "POST",
            "/api/v1/orders",
            body_template={
                "req_id": "REQ-CLI-1",
                "fingerprint": "cli-test-fingerprint",
                "alert_status": "firing",
                "alert_group_name": "CLI Test Alert",
                "labels": {"alertname": "CLITestAlert", "instance": "localhost"},
                "annotations": {"summary": "Created by API CLI tester"},
                "starts_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
        Endpoint("Get order by id", "GET", "/api/v1/orders/{order_id}"),
        Endpoint(
            "Update order",
            "PUT",
            "/api/v1/orders/{order_id}",
            body_template={"processing_status": "processing"},
        ),
    ],
    "Dishes": [
        Endpoint("Cook dishes for order", "POST", "/api/v1/dishes/cook/{order_id}"),
        Endpoint("List dishes", "GET", "/api/v1/dishes", default_query={"limit": 50, "offset": 0}),
        Endpoint("Claim dish", "POST", "/api/v1/dishes/{dish_id}/claim"),
        Endpoint(
            "Update dish (PUT)",
            "PUT",
            "/api/v1/dishes/{dish_id}",
            body_template={"processing_status": "processing"},
        ),
        Endpoint(
            "Update dish (PATCH)",
            "PATCH",
            "/api/v1/dishes/{dish_id}",
            body_template={"processing_status": "complete", "status": "succeeded"},
        ),
        Endpoint("List dish ingredients", "GET", "/api/v1/dishes/{dish_id}/ingredients"),
        Endpoint(
            "Bulk upsert dish ingredients",
            "POST",
            "/api/v1/dishes/{dish_id}/ingredients/bulk",
            body_template={
                "ingredients": [
                    {
                        "recipe_ingredient_id": 1,
                        "task_id": "core.noop",
                        "st2_execution_id": f"cli-{uuid.uuid4()}",
                        "status": "succeeded",
                        "result": {"stdout": "ok"},
                    }
                ]
            },
        ),
    ],
    "Recipes": [
        Endpoint(
            "List recipes", "GET", "/api/v1/recipes/", default_query={"limit": 50, "offset": 0}
        ),
        Endpoint("Get recipe by id", "GET", "/api/v1/recipes/{recipe_id}"),
        Endpoint("Get recipe by name", "GET", "/api/v1/recipes/by-name/{recipe_name}"),
        Endpoint(
            "Create recipe",
            "POST",
            "/api/v1/recipes/",
            body_template={
                "name": "cli-test-recipe",
                "description": "Recipe from API CLI tester",
                "enabled": True,
                "source_type": "manual",
                "workflow_id": None,
                "workflow_payload": None,
                "workflow_parameters": {},
                "recipe_ingredients": [
                    {
                        "ingredient_id": 1,
                        "step_order": 1,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                    }
                ],
            },
        ),
        Endpoint(
            "Update recipe (PUT)",
            "PUT",
            "/api/v1/recipes/{recipe_id}",
            body_template={"description": "Updated by API CLI tester", "enabled": True},
        ),
        Endpoint(
            "Update recipe (PATCH)",
            "PATCH",
            "/api/v1/recipes/{recipe_id}",
            body_template={"enabled": False},
        ),
        Endpoint("Delete recipe", "DELETE", "/api/v1/recipes/{recipe_id}"),
    ],
    "Ingredients": [
        Endpoint(
            "List ingredients",
            "GET",
            "/api/v1/ingredients/",
            default_query={"limit": 50, "offset": 0},
        ),
        Endpoint("Get ingredient by id", "GET", "/api/v1/ingredients/{ingredient_id}"),
        Endpoint(
            "Get ingredients by recipe id", "GET", "/api/v1/ingredients/by-recipe/{recipe_id}"
        ),
        Endpoint(
            "Get ingredients by recipe name", "GET", "/api/v1/ingredients/by-name/{recipe_name}"
        ),
        Endpoint(
            "Create ingredient",
            "POST",
            "/api/v1/ingredients/",
            body_template={
                "task_id": f"cli.task.{uuid.uuid4().hex[:8]}",
                "task_name": "CLI Test Task",
                "source_type": "manual",
                "is_blocking": True,
                "expected_duration_sec": 60,
                "timeout_duration_sec": 300,
                "retry_count": 0,
                "retry_delay": 5,
                "on_failure": "stop",
                "action_parameters": {},
            },
        ),
        Endpoint(
            "Update ingredient (PUT)",
            "PUT",
            "/api/v1/ingredients/{ingredient_id}",
            body_template={"task_name": "CLI Test Task Updated", "expected_duration_sec": 90},
        ),
        Endpoint(
            "Update ingredient (PATCH)",
            "PATCH",
            "/api/v1/ingredients/{ingredient_id}",
            body_template={"retry_count": 1},
        ),
        Endpoint("Delete ingredient", "DELETE", "/api/v1/ingredients/{ingredient_id}"),
    ],
    "Cook": [
        Endpoint(
            "Execute action/workflow",
            "POST",
            "/api/v1/cook/execute",
            body_template={
                "execution_engine": "stackstorm",
                "execution_target": "core.noop",
                "execution_parameters": {},
            },
        ),
        Endpoint("List executions", "GET", "/api/v1/cook/executions"),
        Endpoint("Get execution", "GET", "/api/v1/cook/executions/{execution_id}"),
        Endpoint("Get execution tasks", "GET", "/api/v1/cook/executions/{execution_id}/tasks"),
        Endpoint("Cancel execution", "PUT", "/api/v1/cook/executions/{execution_id}"),
        Endpoint("Delete execution", "DELETE", "/api/v1/cook/executions/{execution_id}"),
        Endpoint(
            "Register workflow",
            "POST",
            "/api/v1/cook/workflows/register",
            body_template={
                "name": "cli_test_workflow",
                "description": "CLI generated workflow",
                "yaml_content": "version: 1.0\ninput: []\ntasks:\n  noop:\n    action: core.noop\n",
                "pack": "default",
                "overwrite": True,
            },
        ),
        Endpoint("Sync from StackStorm", "POST", "/api/v1/cook/sync"),
        Endpoint("List actions", "GET", "/api/v1/cook/actions"),
        Endpoint("Get action by ref", "GET", "/api/v1/cook/actions/{action_ref}"),
        Endpoint("List packs", "GET", "/api/v1/cook/packs"),
    ],
    "Prometheus": [
        Endpoint("List rules", "GET", "/api/v1/prometheus/rules"),
        Endpoint("List rule groups", "GET", "/api/v1/prometheus/rule-groups"),
        Endpoint("Query metrics", "GET", "/api/v1/prometheus/metrics"),
        Endpoint("List labels", "GET", "/api/v1/prometheus/labels"),
        Endpoint("Label values", "GET", "/api/v1/prometheus/label-values/{label_name}"),
        Endpoint("Prometheus health", "GET", "/api/v1/prometheus/health"),
        Endpoint("Reload Prometheus", "POST", "/api/v1/prometheus/reload"),
        Endpoint(
            "Create Prometheus rule",
            "POST",
            "/api/v1/prometheus/rules",
            body_template={
                "name": "CLITestRule",
                "expr": "up == 0",
                "for": "1m",
                "labels": {"severity": "warning"},
                "annotations": {"summary": "CLI test rule"},
            },
        ),
        Endpoint(
            "Update Prometheus rule",
            "PUT",
            "/api/v1/prometheus/rules/{rule_name}",
            body_template={
                "expr": "up == 0",
                "for": "2m",
                "labels": {"severity": "warning"},
                "annotations": {"summary": "CLI test rule updated"},
            },
        ),
        Endpoint("Delete Prometheus rule", "DELETE", "/api/v1/prometheus/rules/{rule_name}"),
    ],
    "Webhook": [
        Endpoint(
            "Post Alertmanager webhook",
            "POST",
            "/api/v1/webhook",
            body_template={
                "receiver": "default",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "CLITestAlert", "instance": "localhost"},
                        "annotations": {"summary": "CLI webhook test"},
                        "startsAt": datetime.now(timezone.utc).isoformat(),
                        "endsAt": "0001-01-01T00:00:00Z",
                        "generatorURL": "http://prometheus.example",
                        "fingerprint": f"cli-{uuid.uuid4().hex[:12]}",
                    }
                ],
                "groupLabels": {"alertname": "CLITestAlert"},
                "commonLabels": {"alertname": "CLITestAlert"},
                "commonAnnotations": {"summary": "CLI webhook test"},
                "externalURL": "http://alertmanager.example",
                "version": "4",
                "groupKey": "{}:{}",
                "truncatedAlerts": 0,
            },
        )
    ],
}


def prompt(prompt_text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt_text}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def prompt_yes_no(prompt_text: str, default_yes: bool = True) -> bool:
    default = "Y/n" if default_yes else "y/N"
    value = input(f"{prompt_text} ({default}): ").strip().lower()
    if not value:
        return default_yes
    return value in {"y", "yes"}


def prompt_json(
    title: str, template: dict[str, Any] | list[Any] | None
) -> dict[str, Any] | list[Any] | None:
    if template is None:
        return None

    print(f"\n{title} template:")
    print(json.dumps(template, indent=2))
    print("Press Enter to use template, or paste JSON on one line to override.")
    raw = input("JSON override: ").strip()
    if not raw:
        return template
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON ({exc}). Using template.")
        return template
    return parsed


def resolve_path(path_template: str) -> str:
    path = path_template
    vars_found = re.findall(r"{([^}]+)}", path_template)
    for var_name in vars_found:
        value = prompt(f"Enter {var_name}")
        path = path.replace("{" + var_name + "}", value)
    return path


def build_query(default_query: dict[str, Any] | None = None) -> dict[str, Any] | None:
    query: dict[str, Any] = dict(default_query or {})
    print("\nQuery parameters:")
    if query:
        print(f"Current defaults: {query}")
    print("Add/override query params as key=value (blank line to finish)")
    while True:
        row = input("query> ").strip()
        if not row:
            break
        if "=" not in row:
            print("Expected key=value")
            continue
        key, value = row.split("=", 1)
        query[key.strip()] = value.strip()
    return query or None


def print_response(resp: requests.Response) -> None:
    print("\n--- Response ---")
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', '<none>')}")
    try:
        parsed = resp.json()
        print(json.dumps(parsed, indent=2))
    except ValueError:
        text = resp.text
        print(text if text else "<empty>")
    print("----------------\n")


def make_request(
    session: requests.Session,
    base_url: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    internal_api_key: str | None = None,
    timeout: float = 30.0,
) -> None:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"X-Request-ID": f"CLI-{uuid.uuid4()}"}
    if internal_api_key:
        headers["X-Internal-API-Key"] = internal_api_key

    print(f"\n-> {method.upper()} {url}")
    if params:
        print(f"   query: {params}")
    if json_body is not None:
        print(f"   body: {json.dumps(json_body)}")

    try:
        resp = session.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return

    print_response(resp)


def choose_from_list(title: str, items: list[str]) -> int | None:
    print(f"\n{title}")
    for idx, item in enumerate(items, start=1):
        print(f"  {idx}. {item}")
    print("  0. Back")
    choice = prompt("Select")
    if not choice.isdigit():
        return None
    value = int(choice)
    if value == 0:
        return 0
    if 1 <= value <= len(items):
        return value
    return None


def run_group(
    session: requests.Session, base_url: str, group_name: str, internal_api_key: str | None
) -> None:
    endpoints = GROUPS[group_name]
    while True:
        choice = choose_from_list(
            f"{group_name} Endpoints", [f"{e.label} [{e.method} {e.path}]" for e in endpoints]
        )
        if choice is None:
            print("Invalid selection.")
            continue
        if choice == 0:
            return
        endpoint = endpoints[choice - 1]
        path = resolve_path(endpoint.path)
        params = (
            build_query(endpoint.default_query)
            if prompt_yes_no("Add query params?", False)
            else None
        )
        body = (
            prompt_json("Request body", endpoint.body_template)
            if endpoint.method in {"POST", "PUT", "PATCH"}
            else None
        )
        make_request(
            session=session,
            base_url=base_url,
            method=endpoint.method,
            path=path,
            params=params,
            json_body=body,
            internal_api_key=internal_api_key,
        )


def custom_request(session: requests.Session, base_url: str, internal_api_key: str | None) -> None:
    method = prompt("Method", "GET").upper()
    path = prompt("Path (example: /api/v1/health)", "/api/v1/health")
    query = build_query()
    body: dict[str, Any] | list[Any] | None = None
    if method in {"POST", "PUT", "PATCH"} and prompt_yes_no("Include JSON body?", True):
        raw = prompt("JSON body", "{}")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}")
            return
    make_request(
        session=session,
        base_url=base_url,
        method=method,
        path=path,
        params=query,
        json_body=body,
        internal_api_key=internal_api_key,
    )


def main() -> int:
    print("PoundCake API CLI Tester")
    print("========================")
    print("Use this tool against local, port-forwarded, or in-cluster API endpoints.")

    base_url = prompt("Base URL", "http://127.0.0.1:8080")
    internal_api_key = ""
    session = requests.Session()

    while True:
        print("\nMain Menu")
        print("  1. Set base URL")
        print("  2. Set/clear X-Internal-API-Key")
        print("  3. Show session info")
        print("  4. Endpoint groups")
        print("  5. Custom request")
        print("  0. Exit")
        choice = prompt("Select")

        if choice == "1":
            base_url = prompt("Base URL", base_url)
        elif choice == "2":
            if internal_api_key:
                if prompt_yes_no("Clear current internal API key?", True):
                    internal_api_key = ""
                    print("Internal API key cleared.")
            else:
                internal_api_key = prompt("Enter internal API key (blank to cancel)")
                if internal_api_key:
                    print("Internal API key set.")
        elif choice == "3":
            print("\nSession info:")
            print(f"  Base URL: {base_url}")
            print(f"  Internal API key set: {'yes' if internal_api_key else 'no'}")
            cookies = session.cookies.get_dict()
            print(f"  Cookies: {cookies if cookies else '<none>'}")
        elif choice == "4":
            group_names = list(GROUPS.keys())
            group_choice = choose_from_list("Endpoint Groups", group_names)
            if group_choice in (None, 0):
                continue
            run_group(session, base_url, group_names[group_choice - 1], internal_api_key or None)
        elif choice == "5":
            custom_request(session, base_url, internal_api_key or None)
        elif choice == "0":
            print("Bye.")
            return 0
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    sys.exit(main())

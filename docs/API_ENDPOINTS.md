# API Endpoints

This document is the current high-level map of the PoundCake API surface.

For field-level request and response schemas, use the generated OpenAPI view when `config.debug=true`:

- `GET /docs`
- `GET /redoc`
- `GET /openapi.json`

## Base Routes

- `GET /`
- `GET /metrics`

## Versioned API

All application routes below are under `/api/v1`.

### Auth

- `GET /auth/providers`
- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`
- `GET /auth/oidc/login`
- `GET /auth/oidc/callback`
- `POST /auth/device/start`
- `POST /auth/device/poll`
- `GET /auth/principals`
- `GET /auth/bindings`
- `POST /auth/bindings`
- `PATCH /auth/bindings/{binding_id}`
- `DELETE /auth/bindings/{binding_id}`

### Health, Settings, and Observability

- `GET /live`
- `GET /ready`
- `GET /health`
- `GET /stats`
- `GET /settings`
- `GET /observability/overview`
- `GET /observability/activity`
- `GET /communications/activity`
- `GET /activity/suppressed`
- `GET /ticketing/bakery`

### Prometheus

- `GET /prometheus/rules`
- `GET /prometheus/rule-groups`
- `GET /prometheus/metrics`
- `GET /prometheus/labels`
- `GET /prometheus/label-values/{label_name}`
- `GET /prometheus/health`
- `POST /prometheus/reload`
- `POST /prometheus/rules`
- `PUT /prometheus/rules/{rule_name}`
- `DELETE /prometheus/rules/{rule_name}`

### Incidents, Dishes, and Dispatch

- `GET /orders`
- `POST /orders`
- `GET /orders/{order_id}`
- `PUT /orders/{order_id}`
- `POST /orders/{order_id}/dispatch`
- `GET /orders/{order_id}/timeline`
- `GET /dishes`
- `POST /dishes/{dish_id}/claim`
- `POST /dishes/{dish_id}/finalize-claim`
- `PUT /dishes/{dish_id}`
- `PATCH /dishes/{dish_id}`
- `GET /dishes/{dish_id}/ingredients`
- `POST /dishes/{dish_id}/ingredients/bulk`

### Workflows and Actions

- `POST /recipes/`
- `GET /recipes/`
- `GET /recipes/{recipe_id}`
- `GET /recipes/by-name/{recipe_name}`
- `PUT /recipes/{recipe_id}`
- `PATCH /recipes/{recipe_id}`
- `DELETE /recipes/{recipe_id}`
- `POST /ingredients/`
- `GET /ingredients/`
- `GET /ingredients/{ingredient_id}`
- `GET /ingredients/by-name/{recipe_name}`
- `GET /ingredients/by-recipe/{recipe_id}`
- `PUT /ingredients/{ingredient_id}`
- `PATCH /ingredients/{ingredient_id}`
- `DELETE /ingredients/{ingredient_id}`

### Communications Policy and Webhook Intake

- `GET /communications/policy`
- `PUT /communications/policy`
- `POST /webhook`

### Suppressions

- `GET /suppressions`
- `POST /suppressions`
- `GET /suppressions/{suppression_id}`
- `PATCH /suppressions/{suppression_id}`
- `POST /suppressions/{suppression_id}/cancel`
- `GET /suppressions/{suppression_id}/stats`
- `POST /suppressions/run-lifecycle`

### Unified Execution and StackStorm Sync

- `POST /cook/execute`
- `GET /cook/executions`
- `GET /cook/executions/{execution_id}`
- `GET /cook/executions/{execution_id}/tasks`
- `PUT /cook/executions/{execution_id}`
- `DELETE /cook/executions/{execution_id}`
- `POST /cook/workflows/register`
- `POST /cook/sync`
- `GET /cook/packs`

### Repo Sync

- `POST /repo-sync/alert-rules/export`
- `POST /repo-sync/alert-rules/import`
- `DELETE /repo-sync/alert-rules`
- `POST /repo-sync/workflow-actions/export`
- `POST /repo-sync/workflow-actions/import`
- `DELETE /repo-sync/workflow-actions`

## Current Contract Notes

Execution engines:

- `stackstorm`
- `bakery`

Canonical Bakery communication operations:

- `open`
- `notify`
- `update`
- `close`

Legacy Bakery communication operation aliases are still accepted:

- `ticket_create` -> `open`
- `ticket_comment` -> `notify`
- `ticket_update` -> `update`
- `ticket_close` -> `close`

Supported Bakery communication destinations:

- `servicenow`
- `jira`
- `github`
- `pagerduty`
- `rackspace_core`
- `teams`
- `discord`

Provider-config requirements in communications routes:

- `rackspace_core` requires `account_number`
- `jira` requires `project_key`
- `github` requires `owner` and `repo`
- `pagerduty` requires `service_id` and `from_email`
- `servicenow`, `teams`, and `discord` do not require route-level `provider_config`

Alertmanager contract highlights:

- required labels: `alertname`, `group_name`, `severity`
- required annotations: `summary`, `description`
- optional routing and context data stays provider-neutral and is rendered later by the destination mixer

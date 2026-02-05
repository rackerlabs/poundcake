# PoundCake Architecture v0.0.1

## Overview

PoundCake is an auto-remediation framework that bridges Prometheus Alertmanager with StackStorm. It receives alerts from Alertmanager and automatically executes remediation workflows through StackStorm.

## Design Principles

1. **Fast Response**: Webhook returns 202 immediately, processes in background
2. **Complete Audit Trail**: Track alerts from webhook to execution via `req_id`
3. **Stateless Design**: No Redis/Celery dependency, scales horizontally
4. **Schema Versioning**: Alembic migrations for safe upgrades
5. **Clear Separation**: PoundCake handles routing, StackStorm handles execution

## Components

### FastAPI Application
- Webhook receiver with background processing (`pre_heat`)
- RESTful API for alerts, recipes, and ovens
- Health checks and metrics endpoint
- Alembic-based schema migrations (startup)

### Database (MySQL/MariaDB)
- Stores recipes, ingredients, alerts, and ovens
- Tracks alert lifecycle and execution status

### Workers
- **Prep Chef**: Polls for new alerts and triggers baking (`/ovens/bake/{alert_id}`)
- **Chef**: Polls for new ovens and executes StackStorm actions via API bridge
- **Timer**: Polls for in-flight ovens and updates completion status

### StackStorm Integration
- Executes remediation workflows
- Returns execution IDs for tracking
- Requires Redis and RabbitMQ

## Database Schema (Conceptual)

### recipes
Defines remediation workflows and their ingredients.
- `name`, `description`, `enabled`, `created_at`, `updated_at`

### ingredients
Defines tasks inside a recipe.
- `recipe_id`, `task_id`, `task_name`, `task_order`, `is_blocking`
- `st2_action`, `parameters`, `expected_time_to_completion`, `timeout`
- `retry_count`, `retry_delay`, `on_failure`

### alerts
Stores alert intake and lifecycle state.
- `req_id`, `fingerprint`, `alert_status`, `processing_status`
- `alert_name`, `group_name`, `labels`, `annotations`
- `severity`, `instance`, `starts_at`, `ends_at`, `counter`

### ovens
Tracks individual ingredient execution.
- `req_id`, `alert_id`, `recipe_id`, `ingredient_id`
- `processing_status`, `action_id`, `st2_status`
- `started_at`, `completed_at`, `action_result`, `error_message`

## Architecture Diagram

```
Alertmanager
    │ POST /api/v1/webhook
    ▼
PoundCake API
    │ creates/updates alerts (pre_heat)
    ▼
MariaDB
    ▲
    │
Prep Chef ── GET /api/v1/alerts?processing_status=new
    │ POST /api/v1/ovens/bake/{alert_id}
    ▼
MariaDB (ovens)
    ▲
    │
Chef ── GET /api/v1/ovens?processing_status=new
    │ POST /api/v1/stackstorm/execute
    ▼
StackStorm
    ▲
    │
Timer ── GET /api/v1/ovens?processing_status=processing
         PATCH /api/v1/ovens/{id}
```

## Data Flow

### 1. Webhook Reception

```
Alertmanager sends POST /api/v1/webhook
                ↓
PreHeatMiddleware generates req_id
                ↓
pre_heat creates Alert (processing_status="new")
                ↓
Return 202 Accepted immediately
```

**Key Points:**
- Response sent before processing (under 10ms)
- Alert `group_name` defaults to `labels.alertname`
- `group_name` matches `recipe.name`

### 2. Alert Dispatching (Prep Chef)

```
Prep Chef polls: GET /api/v1/alerts?processing_status=new
    ↓
For each alert:
  - Match alert.group_name to recipe.name
  - POST /api/v1/ovens/bake/{alert_id}
  - Creates one oven per recipe ingredient
  - Updates alert (processing_status="processing")
```

### 3. Task Execution (Chef)

```
Chef polls: GET /api/v1/ovens?processing_status=new
    ↓
For each oven (respecting is_blocking dependencies):
  - Extract ingredient.st2_action and parameters
  - POST /api/v1/stackstorm/execute (via API bridge)
  - Update oven (processing_status="processing", action_id=ST2_ID)
```

### 4. Completion Monitoring (Timer)

```
Timer polls: GET /api/v1/ovens?processing_status=processing
    ↓
For each oven:
  - Check StackStorm execution status
  - Update oven (processing_status="complete", st2_status="succeeded")
```

## Request ID Tracking

The `req_id` flows through the entire system:

```
Webhook (generates req_id)
    ↓
Alert (stores req_id)
    ↓
Oven (uses alert's req_id)
    ↓
StackStorm execution (receives req_id in parameters)
```

## Recipe Matching Logic

- `pre_heat` sets `alert_name` from `labels.alertname`
- `group_name` defaults to `alert_name`
- Baking matches `alert.group_name` to `recipe.name`

## Deployment Patterns

### Docker Compose

Single-host deployment with all services.

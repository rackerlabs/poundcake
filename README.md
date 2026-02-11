# PoundCake

An auto-remediation framework that bridges Prometheus Alertmanager with StackStorm through a task-based kitchen architecture.

## Overview

PoundCake receives orders from Prometheus Alertmanager and executes remediation workflows through StackStorm. The API is stateless; background workers handle scheduling, execution, and monitoring.

## Architecture (Current)

```mermaid
sequenceDiagram
    participant AM as Alertmanager
    participant API as PoundCake API
    participant DB as MariaDB
    participant PC as Prep Chef
    participant C as Chef
    participant ST2 as StackStorm
    participant T as Timer
    participant DW as Dishwasher

    Note over AM, API: Phase 1: Intake (pre_heat)
    AM->>API: POST /api/v1/webhook (with X-Request-ID)
    API->>DB: Store Order (processing_status: new)
    API-->>AM: 202 Accepted

    Note over DB, PC: Phase 2: Dispatching (prep-chef)
    PC->>API: GET /api/v1/orders?processing_status=new
    PC->>API: POST /api/v1/dishes/cook/{order_id}
    API->>DB: Create Dish for the Recipe
    API->>DB: Update Order (processing_status: processing)

    Note over DB, C: Phase 3: Execution (chef)
    C->>API: POST /api/v1/dishes/{dish_id}/claim
    C->>API: POST /api/v1/cook/workflows/register
    C->>API: POST /api/v1/cook/execute
    API->>ST2: POST /v1/executions (workflow)
    ST2-->>API: execution_id
    API-->>C: workflow_execution_id
    C->>API: PATCH /api/v1/dishes/{id} (processing_status: processing)

    Note over ST2, T: Phase 4: Monitoring (timer)
    T->>API: GET /api/v1/dishes?processing_status=processing
    T->>API: POST /api/v1/dishes/{dish_id}/finalize-claim
    T->>API: GET /api/v1/cook/executions/{workflow_execution_id}/tasks
    T->>API: POST /api/v1/dishes/{dish_id}/ingredients/bulk
    T->>API: PATCH /api/v1/dishes/{id} (processing_status: complete/failed)

    Note over API, DW: Phase 5: Sync (dishwasher)
    DW->>API: POST /api/v1/cook/sync
    API->>DB: Upsert Ingredients/Recipes
```

## Concurrency Guarantees (Locks and Claims)

```mermaid
flowchart TD
    A["Alertmanager webhook"] --> B["pre_heat: select (fingerprint, is_active) FOR UPDATE"]
    B --> C["orders (new)"]
    C --> D["prep-chef: cook_dishes"]
    D --> E["orders new -> processing (atomic update)"]
    D --> F["dishes created (new)"]
    F --> G["chef: claim_dish"]
    G --> H["dishes new -> processing (atomic update)"]
    H --> I["timer: finalize-claim"]
    I --> J["dishes processing -> finalizing (atomic update)"]
    J --> K["timer: finalize + status update"]
```

## Components

- **PoundCake API**: FastAPI entry point for webhooks, recipe management, and StackStorm bridge.
- **Prep Chef**: Polls for new orders, creates a Dish per order.
- **Chef**: Claims dishes, registers workflows, executes StackStorm workflows.
- **Timer**: Monitors StackStorm workflow execution and records results.
- **Dishwasher**: Periodically syncs StackStorm actions and packs into Ingredients/Recipes.
- **StackStorm**: Executes remediation workflows.
- **MariaDB**: Central state store.

## Data Model (Core Tables)

- `orders`: Alertmanager intake and processing status.
- `ingredients`: StackStorm actions and defaults.
- `recipes`: Workflow templates and payloads.
- `recipe_ingredients`: Ordered ingredients for a recipe.
- `dishes`: Execution instance for a recipe/order.
- `dish_ingredients`: Per-task execution data (task_id, st2_execution_id, status, timestamps, result).

## Quick Start (Docker Compose)

```bash
# Start all services

docker compose up -d

# Health
curl http://localhost:8000/api/v1/health

# Logs

docker compose logs -f api prep-chef chef timer dishwasher
```

Services:
- PoundCake API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs` (debug only)
- StackStorm API: `http://localhost:9101`

## Configuration

Important environment variables:

```bash
# Database
DATABASE_URL=mysql+pymysql://user:pass@poundcake-mariadb:3306/poundcake

# StackStorm
POUNDCAKE_STACKSTORM_URL=http://stackstorm-api:9101
POUNDCAKE_ST2_PACK_ROOT=/app/stackstorm-packs
```

`config/st2_api_key` is created by `st2client` during bootstrap.

## API Reference

See `docs/API_ENDPOINTS.md` or `API_ENDPOINTS.txt`.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.

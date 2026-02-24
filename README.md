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
    AM->>API: POST /api/v1/webhook (with X-Internal-API-Key header)
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
- **Suppression Lifecycle (via Timer)**: Finalizes ended suppression windows and creates/auto-closes summary tickets through Bakery.
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
- `alert_suppressions`: Time-windowed suppression windows (`scope=all|matchers`).
- `alert_suppression_matchers`: Label-matcher rules (`eq|neq|regex|nregex|exists|not_exists`).
- `suppressed_events`: Suppressed webhook events (audit trail).
- `suppression_summaries`: Aggregated suppression stats + Bakery summary ticket create/close refs.

## Alert Suppression

- Suppression matching is evaluated in webhook receive-time order before order creation.
- If an alert matches an active suppression window, PoundCake records the suppressed event and does not create/update/cancel orders for that alert event.
- Overlapping windows use first-created attribution (`created_at ASC`), and each event is counted once.
- Ended windows are summarized by lifecycle processing and generate a Bakery summary ticket which is immediately auto-closed after create succeeds.

## Workflow Graph Generation (DB -> Orquesta)

### Columns used by YAML generation

- `recipes.name`, `recipes.description` -> workflow metadata (`description` fallback uses `name`)
- `recipe_ingredients.step_order` -> task ordering and task key prefix (`step_{n}_...`)
- `recipe_ingredients.depth` -> explicit stage ordering when any depth > 0
- `recipe_ingredients.input_parameters` -> task `input`
- `ingredients.task_id` -> task `action`
- `ingredients.task_name` -> task key suffix
- `ingredients.is_blocking` -> stage grouping when no explicit depth is used
- `ingredients.retry_count`, `ingredients.retry_delay` -> task `retry`

### Mixed blocking/non-blocking scenario

Example scenario:

- Task 1 is blocking
- Tasks 2-4 are non-blocking (parallel fork)
- Task 5 is blocking (fan-in)

```mermaid
flowchart LR
    T1["step_1_task1 (blocking)"]
    T2["step_2_task2 (non-blocking)"]
    T3["step_3_task3 (non-blocking)"]
    T4["step_4_task4 (non-blocking)"]
    T5["step_5_task5 (blocking, join: all)"]

    T1 -->|"when: succeeded(), do: [T2,T3,T4]"| T2
    T1 --> T3
    T1 --> T4

    T2 -->|"when: succeeded(), do: T5"| T5
    T3 -->|"when: succeeded(), do: T5"| T5
    T4 -->|"when: succeeded(), do: T5"| T5
```

### Mapping diagram

```mermaid
flowchart TB
    RI["recipe_ingredients (step_order, depth, input_parameters)"]
    ING["ingredients (task_id, task_name, is_blocking, retry_count, retry_delay)"]
    REC["recipes (name, description)"]
    GEN["generate_orquesta_yaml()"]
    YAML["Orquesta YAML (tasks, next, when, do, join)"]

    RI --> GEN
    ING --> GEN
    REC --> GEN
    GEN --> YAML
```

### YAML sample (StackStorm 3.9 Orquesta style)

```yaml
version: "1.0"
description: "Mixed blocking/non-blocking example"
tasks:
  step_1_task1:
    action: core.local
    input:
      cmd: 'echo "step 1"'
    next:
      - when: <% succeeded() %>
        do:
          - step_2_task2
          - step_3_task3
          - step_4_task4

  step_2_task2:
    action: core.local
    input:
      cmd: 'echo "step 2"'
    next:
      - when: <% succeeded() %>
        do: step_5_task5

  step_3_task3:
    action: core.local
    input:
      cmd: 'echo "step 3"'
    next:
      - when: <% succeeded() %>
        do: step_5_task5

  step_4_task4:
    action: core.local
    input:
      cmd: 'echo "step 4"'
    next:
      - when: <% succeeded() %>
        do: step_5_task5

  step_5_task5:
    action: core.local
    input:
      cmd: 'echo "step 5"'
    join: all

output:
  result: <% task(step_5_task5).result %>
```

## Installation

### Unified Launchers

```bash
# Install via Docker Compose
./install/install-poundcake-docker.sh

# Install via Helm
./install/install-poundcake-helm.sh
```

### Helm Install

```bash
# Helm-based install script
./helm/bin/install-poundcake.sh

# Optional: pass extra Helm args through
./helm/bin/install-poundcake.sh -f /path/to/values.yaml

# Validate chart rendering before install
./helm/bin/install-poundcake.sh --validate
```

Installer flags:

- `--validate` runs `helm lint` + `helm template --debug` before install
- `--skip-preflight` skips dependency and cluster connectivity checks
- `--rotate-secrets` deletes known chart-managed secrets before install

Detailed Helm startup gate flow: see `/Users/chris.breu/code/poundcake/helm/README.md` under **Startup Order**.

### Helm Install With Private GHCR Images

```bash
source ./install/set-env-helper.sh
export HELM_REGISTRY_USERNAME="<gh-username>"
export HELM_REGISTRY_PASSWORD="<github_pat_with_read_packages>"
# Optional OCI chart source override; helper defaults to local chart install (./helm)
# export POUNDCAKE_CHART_REPO="oci://ghcr.io/<owner>/charts/poundcake"
./install/install-poundcake-helm.sh
```

Installer env controls for private pulls:

- `POUNDCAKE_IMAGE_PULL_SECRET_NAME` (default: `ghcr-pull`)
- `POUNDCAKE_CREATE_IMAGE_PULL_SECRET` (default: `true`)
- `POUNDCAKE_IMAGE_PULL_SECRET_EMAIL` (default: `noreply@local`)
- `POUNDCAKE_IMAGE_PULL_SECRET_ENABLED` (default: `true`)

Chart value controls:

- Canonical (PoundCake-only): `poundcakeImage.pullSecrets`
- Legacy fallback (temporary): `imagePullSecrets`

Troubleshooting `ErrImagePull` / GHCR `401 Unauthorized`:

- Ensure image pin is explicit via either:
  - `POUNDCAKE_IMAGE_REPO:POUNDCAKE_IMAGE_TAG`, or
  - `POUNDCAKE_IMAGE_REPO@POUNDCAKE_IMAGE_DIGEST`
- Ensure `HELM_REGISTRY_USERNAME`/`HELM_REGISTRY_PASSWORD` are set
- Ensure PAT has `read:packages` and package visibility grants access
- Verify pull secret is on a PoundCake pod:
  `kubectl -n <namespace> get pod <poundcake-pod> -o jsonpath='{.spec.imagePullSecrets[*].name}'`

OCI chart auth fallback chain used by the installer:

- Username: `HELM_REGISTRY_USERNAME` -> `GHCR_USERNAME` -> `GITHUB_ACTOR`
- Password: `HELM_REGISTRY_PASSWORD` -> `GHCR_TOKEN` -> `CR_PAT` -> `GITHUB_TOKEN`

Default Helm namespace is `rackspace` (override with `POUNDCAKE_NAMESPACE`).
Startup jobs are hook-driven (`post-install,post-upgrade`), so the installer defaults to
`POUNDCAKE_HELM_WAIT=false` to avoid deadlocks with marker-gated init containers.
If you force wait semantics (`--wait`/`--atomic`), set `POUNDCAKE_ALLOW_HOOK_WAIT=true`
or the installer will exit with a deadlock guard error.

If a rollout gets stuck in `Init`, re-run without wait semantics:

```bash
POUNDCAKE_HELM_WAIT=false ./install/install-poundcake-helm.sh
kubectl -n rackspace get jobs
```

StackStorm service startup now renders runtime config at `/tmp/st2/st2.conf` to avoid non-root writes to `/etc`.
Successful startup hook jobs are auto-cleaned by default; failed ones are retained for debugging.

One-time cleanup for existing completed startup jobs:

```bash
kubectl -n rackspace get jobs \
  -o jsonpath='{range .items[?(@.status.succeeded==1)]}{.metadata.name}{"\n"}{end}' \
  | grep -E '^(stackstorm-.*ready|stackstorm-mongodb-user-sync|stackstorm-startup-markers-reset|stackstorm-bootstrap|poundcake-.*)$' \
  | xargs -r -I{} kubectl -n rackspace delete job {}
kubectl -n rackspace get jobs,pods
```

### Docker Compose Install

```bash
# Docker-based install script
./docker/bin/install-poundcake.sh
```

### Docker Compose Quick Start

```bash
# Start all services

docker compose -f docker/docker-compose.yml up -d

# Health
curl http://localhost:8000/api/v1/health

# Logs

docker compose -f docker/docker-compose.yml logs -f api prep-chef chef timer dishwasher
docker compose -f docker/docker-compose.yml logs -f api prep-chef chef timer dishwasher
```

#### Docker Compose Dependency Gates

```mermaid
flowchart LR
  mongodb["stackstorm-mongodb"] -->|service_healthy| st2api["stackstorm-api"]
  rabbitmq["stackstorm-rabbitmq"] -->|service_healthy| st2api
  redis["stackstorm-redis"] -->|service_healthy| st2api

  st2api -->|service_healthy| st2auth["stackstorm-auth"]
  st2api -->|service_healthy| st2bootstrap["stackstorm-bootstrap"]
  st2auth -->|service_healthy| st2bootstrap

  packinit["poundcake-pack-init"] -->|service_completed_successfully| api["api"]
  mariadb["mariadb"] -->|service_healthy| api
  st2api -->|service_healthy| api

  api -->|service_started| pcbootstrap["poundcake-bootstrap"]
  packinit -->|service_completed_successfully| pcbootstrap
  st2api -->|service_healthy| pcbootstrap

  api -->|service_healthy| chef["chef"]
  api -->|service_healthy| prepchef["prep-chef"]
  api -->|service_healthy| timer["timer"]
  api -->|service_healthy| dishwasher["dishwasher"]
  pcbootstrap -->|service_completed_successfully| chef
  pcbootstrap -->|service_completed_successfully| prepchef
  pcbootstrap -->|service_completed_successfully| timer
  pcbootstrap -->|service_completed_successfully| dishwasher
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
# StackStorm packs are served by API endpoint /api/v1/cook/packs
# and synchronized into StackStorm pods by the pack-sync sidecar.
# Legacy compatibility endpoint /api/v1/internal/stackstorm/pack.tgz remains
# temporarily available and will be removed after a migration window.
```

`config/st2_api_key` is created by `st2client` during bootstrap.

## API/Bakery Database Separation

PoundCake API and Bakery must keep separate database ownership:
- API uses the PoundCake migration stream in `/Users/chris.breu/code/poundcake/alembic`.
- Bakery uses the Bakery migration stream in `/Users/chris.breu/code/poundcake/bakery/alembic`.

In alongside deployments, both services may share the same MariaDB server endpoint, but must use different database names and credentials.

## Container Build Targets

The root Dockerfile publishes separate runtime targets:
- `api-runtime` -> `ghcr.io/.../poundcake`
- `bakery-runtime` -> `ghcr.io/.../poundcake-bakery`

UI remains built from `/Users/chris.breu/code/poundcake/ui/Dockerfile` and published as `ghcr.io/.../poundcake-ui`.

## Alertmanager Integration (Kubernetes)

When PoundCake auth is enabled, Alertmanager must send the `X-Internal-API-Key` header.

Get the key:

```bash
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.internal-api-key}' | base64 -d
```

Webhook URL (in-cluster):

```text
http://poundcake.rackspace.svc.cluster.local:8080/api/v1/webhook
```

Example `alertmanager.yml` receiver:

```yaml
receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake.rackspace.svc.cluster.local:8080/api/v1/webhook
        send_resolved: true
        http_config:
          headers:
            X-Internal-API-Key: "<internal-api-key>"
```

Example Prometheus Operator `AlertmanagerConfig` receiver:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: poundcake
  namespace: prometheus
spec:
  route:
    receiver: poundcake
    groupBy: ["alertname"]
  receivers:
    - name: poundcake
      webhookConfigs:
        - url: http://poundcake.rackspace.svc.cluster.local:8080/api/v1/webhook
          sendResolved: true
          httpConfig:
            headers:
              X-Internal-API-Key: "<internal-api-key>"
```

If the header/key is missing, PoundCake returns `401` for `/api/v1/webhook`.

## API Reference

See `docs/API_ENDPOINTS.md`.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.

## Developer Workflow

See `docs/developer.md` for fork-based package publishing and lab deployment steps.

# PoundCake

An auto-remediation framework that bridges Prometheus Alertmanager with execution engines through a task-based kitchen architecture.

## Overview

PoundCake receives orders from Prometheus Alertmanager and executes remediation workflows through a unified execution orchestrator (StackStorm and Bakery). The API is stateless; background workers handle scheduling, execution, and monitoring.

## Documentation

- Source docs live in [`docs/`](./docs).
- Local preview:
  - `source .venv/bin/activate`
  - `pip install -r dev-requirements.txt`
  - `mkdocs serve`
- Strict local build:
  - `mkdocs build --strict`
- GitHub Pages is built from the MkDocs site via the docs Pages workflow.

## Architecture (Current)

```mermaid
flowchart LR
  classDef system fill:#eef6ff,stroke:#5b7ea3;
  classDef store fill:#fdf6e3,stroke:#657b83;
  classDef worker fill:#eef7ea,stroke:#6b8f5e;

  subgraph Intake
    AM["Alertmanager"] --> API["PoundCake API"]
    API --> DB["MariaDB"]
  end

  subgraph Dispatch
    PC["prep chef"] --> API
    API --> Dish["dish row"]
    API --> Order["order processing"]
  end

  subgraph Execute
    Chef["chef"] --> API
    API --> ST2["StackStorm"]
    Timer["timer"] --> API
  end

  subgraph Sync
    DW["dishwasher"] --> API
    API --> Catalog["recipes and ingredients"]
  end

  class API,AM,ST2 system;
  class DB,Dish,Order,Catalog store;
  class PC,Chef,Timer,DW worker;
```

## Unified Dispatch Order Diagram

```mermaid
flowchart LR
  classDef api fill:#eef6ff,stroke:#5b7ea3;
  classDef worker fill:#eef7ea,stroke:#6b8f5e;
  classDef state fill:#fdf6e3,stroke:#657b83;

  Firing["firing webhook"] --> Preheat["pre heat"]
  Resolved["resolved webhook"] --> Preheat

  subgraph Dispatch
    Preheat --> Queue["dispatchable order"]
    Prep["prep chef"] --> Queue
    Queue --> Phase{"run phase"}
    Phase --> FireDish["firing dish"]
    Phase --> ResolveDish["resolving dish"]
  end

  subgraph Execution
    FireDish --> Claim["chef claims dish"]
    ResolveDish --> Claim
    Claim --> Stackstorm{"stackstorm rows"}
    Stackstorm -->|yes| ST2["run stackstorm"]
    Stackstorm -->|no| Bakery{"bakery rows"}
    ST2 --> Timer["timer writes results"]
    Timer --> Bakery
    Bakery -->|yes| Bake["run bakery rows"]
    Bakery -->|no| Final["finalize dish"]
    Bake --> Final
  end

  Final --> Outcome{"dish phase"}
  Outcome -->|firing| OrderUpdate["update active order"]
  Outcome -->|resolving| OrderClose["complete or fail order"]

  class Preheat,Claim,ST2,Timer,Bake api;
  class Prep worker;
  class Queue,FireDish,ResolveDish,Final,OrderUpdate,OrderClose state;
```

## Concurrency Guarantees (Locks and Claims)

```mermaid
flowchart TD
    Hook["webhook"] --> Lock["pre heat lock"]
    Lock --> Order["order new"]
    Order --> Dispatch["prep chef dispatch"]
    Dispatch --> OrderRun["order processing"]
    Dispatch --> Dish["dish new"]
    Dish --> Claim["chef claim"]
    Claim --> DishRun["dish processing"]
    DishRun --> Finalize["timer finalize claim"]
    Finalize --> DishFinal["dish finalizing"]
    DishFinal --> Result["timer stores result"]
```

## Order Processing Status Lifecycle

| From | Event | To | Notes |
|---|---|---|---|
| `new` | `prep-chef -> /orders/{order_id}/dispatch` | `processing` | Atomic transition when dish creation is claimed. |
| `processing` | Dish reaches terminal (`complete/failed/...`) | `resolving` | Triggered by dish update path for non-catch-all, non-terminal orders. |
| `new` or `processing` | Alertmanager sends `resolved` | `resolving` | Resolve-phase orchestration is initiated by pre-heat. |
| `resolving` | `prep-chef -> /orders/{order_id}/dispatch` | `complete` | Resolve flow is comms-only (Bakery); StackStorm rows are not seeded in resolving. |
| `complete`/`failed`/`canceled` | Any webhook/timer follow-up | unchanged | Terminal statuses are immutable and not re-opened by side effects. |

## Communications Policy

- Communications are policy-driven, not authored as ordinary workflow steps in the default UI path.
- A global communications policy is optional and is managed from `Configuration -> Global Communications`.
- A workflow can be enabled only if it has effective communications from one of these sources:
  - the global default
  - a workflow-specific local override
- Workflow-local communications replace the global default for that workflow.
- Any enabled route type is valid. Ticket-backed and chat-only routes both count.

### Runtime lifecycle

- Workflow start: no communication is created just because remediation started.
- Failed remediation or escalation: PoundCake issues `open` on each effective route and leaves it open.
- Successful auto-remediation after the alert clears: PoundCake issues `open` and then `close` on each effective route.
- Alert clears after escalation: PoundCake issues `update` on existing routes and leaves them open.
- No matching workflow: fallback communications use the global route set, issuing `open` immediately and `update` when the alert clears.

### Configuration model

- `Global Communications` defines the shared default route set for Core, Teams, Discord, or any other supported Bakery destination.
- `Workflows` choose `Use global default` or `Use workflow-specific communications`.
- `Actions` are for remediation and utility steps. Communication routes are configured in the communications policy editors instead of as normal workflow actions.
- Managed policy artifacts are stored internally as hidden Bakery-backed ingredients and recipe steps and are not shown in the normal workflow/action inventories.

## Order Workflow Graph (States + Bakery Calls)

```mermaid
flowchart LR
  classDef active fill:#eef7ea,stroke:#6b8f5e;
  classDef terminal fill:#fce8e6,stroke:#a35b5b;

  New["new"] --> Processing["processing"]
  New --> Resolving["resolving"]
  Processing --> Resolving
  Resolving --> Processing
  Resolving --> Complete["complete"]
  Resolving --> Failed["failed"]
  New --> Canceled["canceled"]
  Processing --> Canceled
  Resolving --> Canceled

  class New,Processing,Resolving active;
  class Complete,Failed,Canceled terminal;
```

For the current function-by-function webhook flow, Bakery handoff chain, and terminal state map, see [Architecture](./docs/architecture.md).

## Components

- **PoundCake API**: FastAPI entry point for webhooks, recipe management, and unified execution orchestration.
- **Prep Chef**: Polls for new orders, creates a Dish per order.
- **Chef**: Claims dishes, registers workflows, executes StackStorm workflows.
- **Timer**: Monitors StackStorm workflow execution and records results.
- **Suppression Lifecycle (via Timer)**: Finalizes ended suppression windows and creates/auto-closes summary tickets through Bakery.
- **Dishwasher**: Periodically syncs StackStorm actions and packs into Ingredients/Recipes.
  During `poundcake-bootstrap`, sync also loads bootstrap Bakery comms ingredients from
  `config/bootstrap/ingredients/bakery.yaml` (runtime path `/app/bootstrap/ingredients/bakery.yaml`)
  and bootstrap recipe catalog entries from `config/bootstrap/recipes/*.yaml`
  (runtime directory `/app/bootstrap/recipes`).
- **StackStorm**: Executes remediation workflows.
- **MariaDB**: Central state store.

## Data Model (Core Tables)

- `orders`: Alertmanager intake and processing status.
- `ingredients`: StackStorm actions and defaults.
- `recipes`: Workflow templates and payloads.
- `recipe_ingredients`: Ordered ingredients for a recipe.
- communications policy internals are stored as hidden Bakery-backed ingredients and recipe steps; the user-facing UI exposes them as global or workflow-specific communication routes.
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
- `ingredients.execution_target` -> task `action`
- `ingredients.task_key_template` -> task key suffix
- `ingredients.execution_purpose` -> execution role (`remediation|utility|comms`)
- `ingredients.execution_id` -> template execution identifier metadata
- `ingredients.execution_payload` -> JSON object payload template/metadata (`object | null`)
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

# Install PoundCake via Helm
./install/install-poundcake-helm.sh

# Install Bakery via Helm
./install/install-bakery-helm.sh
```

### Helm Install

```bash
# PoundCake installer (PoundCake-only)
./helm/bin/install-poundcake.sh

# Bakery installer (Bakery-only)
./helm/bin/install-bakery.sh

# Optional: pass extra Helm args through
./helm/bin/install-poundcake.sh -f /path/to/values.yaml

# Validate chart rendering before install
./helm/bin/install-poundcake.sh --validate

# Bakery secret bootstrap from CLI credentials (non-interactive)
./helm/bin/install-bakery.sh \
  --bakery-rackspace-url https://ws.core.rackspace.com \
  --bakery-rackspace-username poundcake \
  --bakery-rackspace-password '<password>'

# Add chat/webhook routes using the same installer-managed secret flow
./helm/bin/install-bakery.sh \
  --bakery-active-provider teams \
  --bakery-teams-webhook-url '<teams-webhook-url>' \
  --bakery-discord-webhook-url '<discord-webhook-url>'
```

Installer flags:

- `--validate` runs `helm lint` + `helm template --debug` before install
- `--skip-preflight` skips dependency and cluster connectivity checks
- `--rotate-secrets` deletes known chart-managed secrets before install
- `--remote-bakery-url` configures PoundCake to use an external/co-located Bakery endpoint
- `--remote-bakery-auth-secret` sets the PoundCake Bakery HMAC client secret for external Bakery endpoints
- `--shared-db-mode <auto|on|off>` and `--shared-db-server-name` control shared MariaDB mode for PoundCake
- Bakery installer verifies or creates provider secrets for Rackspace Core, ServiceNow, Jira, GitHub, PagerDuty, Teams, and Discord, then wires `bakery.<provider>.existingSecret` automatically when those secrets exist
- Use `--update-bakery-secret` to rotate/update an existing Bakery provider secret
- Bakery installer also creates/reuses a Bakery HMAC auth secret and wires it into Bakery API/client auth values
- PoundCake installer auto-discovers the colocated Bakery HMAC secret; external remote Bakery requires an explicit `--remote-bakery-auth-secret`
- Rackspace Core credentials/URL via `values.yaml` are disabled for Bakery; use `bakery.rackspaceCore.existingSecret` (installer-managed secret) instead
- Bakery-only install deploys Bakery API + Bakery worker + Bakery DB init job
- For repeatable Bakery deploys, prefer `POUNDCAKE_BAKERY_IMAGE_DIGEST` (or `POUNDCAKE_IMAGE_DIGEST` fallback) and ensure image pull auth is configured (`POUNDCAKE_CREATE_IMAGE_PULL_SECRET` or existing pull secret via `POUNDCAKE_IMAGE_PULL_SECRET_NAME`)

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
- Bakery precedence is `POUNDCAKE_BAKERY_IMAGE_DIGEST` -> `POUNDCAKE_BAKERY_IMAGE_TAG` -> chart defaults, with `POUNDCAKE_IMAGE_DIGEST` used when Bakery digest is unset.
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

# Authentication
# Helm auth.enabled maps to runtime POUNDCAKE_AUTH_ENABLED on API/bootstrap workloads.
POUNDCAKE_AUTH_ENABLED=true

# StackStorm
POUNDCAKE_STACKSTORM_URL=http://stackstorm-api:9101
# StackStorm packs are served by API endpoint /api/v1/cook/packs
# and synchronized into StackStorm pods by the pack-sync sidecar.
```

`config/st2_api_key` is created during StackStorm bootstrap and projected into `stackstorm-client` for `st2api` interactions.

## API/Bakery Database Separation

PoundCake API and Bakery must keep separate database ownership:
- API uses the PoundCake migration stream in `/Users/chris.breu/code/poundcake/alembic`.
- Bakery uses the Bakery migration stream in `/Users/chris.breu/code/poundcake/bakery/alembic`.

For same-namespace co-location, deploy in this order:
1. `./install/install-bakery-helm.sh`
2. `./install/install-poundcake-helm.sh`

In co-located deployments, both services may share the same MariaDB server endpoint, but they must use separate database/schema ownership and separate credentials.

If Bakery is not co-located, configure PoundCake with an explicit external Bakery URL:

```bash
./install/install-poundcake-helm.sh --remote-bakery-url https://bakery.example.com
```

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

See `docs/api_endpoints.md`.

## Troubleshooting

See `docs/troubleshooting.md`.

## Developer Workflow

See `docs/developer.md` for fork-based package publishing and lab deployment steps.

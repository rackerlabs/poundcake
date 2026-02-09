# PoundCake

An auto-remediation framework that bridges Prometheus Alertmanager with StackStorm through a task-based "Bakery" architecture.

## Overview

PoundCake receives alerts from Prometheus Alertmanager and automatically executes remediation workflows through StackStorm. It is designed for high-throughput with a stateless API and background workers that handle task sequencing and monitoring.

## Architecture

```mermaid
sequenceDiagram
    participant AM as Alertmanager
    participant API as PoundCake API
    participant DB as MariaDB
    participant OD as Prep Chef
    participant OE as Chef
    participant ST2 as StackStorm
    participant T as Timer

    Note over AM, API: Phase 1: Intake (pre_heat)
    AM->>API: POST /api/v1/webhook (with X-Request-ID)
    API->>DB: Store Alert (processing_status: new)
    API-->>AM: 202 Accepted

    Note over DB, OD: Phase 2: Dispatching (prep-chef)
    OD->>API: GET /api/v1/alerts?processing_status=new
    OD->>API: POST /api/v1/ovens/bake/{alert_id} (with X-Request-ID)
    API->>DB: Create Oven tasks from Recipe Ingredients
    API->>DB: Update Alert (processing_status: processing)

    Note over DB, OE: Phase 3: Execution (chef)
    OE->>API: GET /api/v1/ovens?processing_status=new (returns OvenDetailResponse with ingredient data)
    OE->>API: POST /api/v1/stackstorm/execute (st2_action + parameters from ingredient)
    API->>ST2: POST /v1/executions (Start Action)
    ST2-->>API: Execution ID
    API-->>OE: Execution ID
    OE->>API: PATCH /api/v1/ovens/{id} (processing_status: processing, action_id: ST2_ID)

    Note over ST2, T: Phase 4: Monitoring (timer)
    T->>API: GET /api/v1/ovens?processing_status=processing
    T->>ST2: GET /v1/executions/{action_id}
    ST2-->>T: Status: succeeded
    T->>API: PATCH /api/v1/ovens/{id} (processing_status: complete, st2_status: succeeded)

    Note over API, DB: All operations correlated via X-Request-ID for end-to-end tracing
```

### Components

- **PoundCake API**: FastAPI entry point for webhooks, recipe management, and StackStorm bridge. Returns 202 Accepted for async processing.
- **Prep Chef (prep-chef)**: Background service that polls for new alerts, matches them to recipes, and "bakes" them into oven tasks by creating one oven per ingredient.
- **Chef (chef)**: Worker that polls for new oven tasks, respects is_blocking dependencies, and triggers StackStorm actions via the API bridge.
- **Timer**: Monitor service that polls StackStorm for execution completion status and updates oven records with final results.
- **StackStorm (st2)**: The automation engine that performs the actual remediation actions (accessed via PoundCake API bridge).
- **MariaDB**: Central state store for alerts, recipes, ingredients, and oven task tracking with full audit trail via req_id.

### Container Architecture

```
┌─────────────────┐
│  Alertmanager   │
└────────┬────────┘
         │ Webhook
         ↓
┌─────────────────┐     ┌──────────────┐
│  poundcake-api  │────→│   MariaDB    │
│  (Port 8000)    │     │              │
└────────┬────────┘     └──────────────┘
         │ Polls API
         ↓
┌──────────────────┐
│ prep-chef        │  Dispatcher: alerts → ovens
│ (prep_chef.py)   │
└────────┬─────────┘
         │ Polls API
         ↓
┌──────────────────┐    ┌──────────────┐
│  chef            │───→│  StackStorm  │
│  (chef.py)       │    │  (Full Stack)│
└────────┬─────────┘    └──────────────┘
         │                      ↑
         ↓                      │
┌──────────────────┐           │
│  timer           │───────────┘
│  (timer.py)      │  Monitors completions
└──────────────────┘
```

All services communicate through the PoundCake API (no direct database or ST2 access from workers).

## Quick Start

### Docker Compose

```bash
# Clone repository
git clone https://github.com/yourorg/poundcake.git
cd poundcake

# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/api/v1/health

# View logs
docker compose logs -f api prep-chef chef timer
```

Containers:
- **poundcake-api** - API server (webhooks, recipes, ST2 bridge)
- **poundcake-prep-chef** - Dispatcher (alerts → ovens)
- **poundcake-chef** - Executor (ovens → ST2 actions)
- **poundcake-timer** - Monitor (tracks completions)
- Plus: MariaDB, StackStorm (MongoDB, Redis, RabbitMQ, API, Auth, Workers)

Services:
- PoundCake API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- StackStorm API: http://localhost:9101 (requires ST2_API_KEY)
- RabbitMQ Management: http://localhost:15672 (guest/guest)

### Kubernetes/Helm

```bash
# Add helm repository
helm repo add poundcake https://yourorg.github.io/poundcake

# Install with external StackStorm
helm install poundcake poundcake/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake" \
  --set stackstorm.url="http://st2api.stackstorm.svc:9101" \
  --set stackstorm.apiKey="your-api-key"

# Or with embedded Redis and RabbitMQ
helm install poundcake poundcake/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set stackstorm.redis.enabled=true \
  --set stackstorm.rabbitmq.enabled=true \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake"
```

#### Hardened Kubernetes Environments (Talos, etc.)

PoundCake automatically configures namespace-level Pod Security Standards during Helm install/upgrade. This eliminates PodSecurity warnings in hardened Kubernetes distributions without requiring manual namespace configuration.

The Helm chart includes a pre-install/pre-upgrade hook that sets:
```yaml
pod-security.kubernetes.io/enforce: baseline
pod-security.kubernetes.io/audit: baseline
pod-security.kubernetes.io/warn: baseline
```

The `baseline` Pod Security Standard is appropriate for common workloads including databases, web servers, and application containers, providing strong security while maintaining compatibility with standard container images.

**Note**: If you see PodSecurity warnings during deployment, they are informational only and do not prevent the chart from installing successfully. The namespace configuration job handles this automatically on the next install/upgrade.

## Features

- **Fast Response**: Webhook returns 202 Accepted immediately, processes asynchronously
- **Auto-Migration**: Alembic migrations run automatically on startup with belt-and-suspenders approach
- **Complete Audit Trail**: Track alerts from webhook to completion via req_id across all services
- **Stateless API**: No Redis/Celery dependency for PoundCake, scales horizontally
- **Recipe System**: Multi-step workflows with task dependencies (is_blocking) and parameters
- **Service Separation**: Dedicated containers for dispatching, execution, and monitoring
- **Clean Startup**: Health checks with startup waits, no noisy error logs
- **API Bridge**: Unified StackStorm access through PoundCake API (no direct ST2 credentials in workers)
- **Health Checks**: Built-in endpoint for container health probes
- **API Documentation**: Interactive Swagger docs at `/docs`

## Database Setup

PoundCake uses Alembic for database schema management.

```bash
# Run migrations (creates all tables)
python api/migrate.py upgrade

# Check current version
python api/migrate.py current

# Create new migration
python api/migrate.py create "description"
```

See [docs/DATABASE_MIGRATIONS.md](docs/DATABASE_MIGRATIONS.md) for details.

## Configuration

### Environment Variables

**PoundCake API:**
```bash
# Database (required)
POUNDCAKE_DATABASE_URL=mysql+pymysql://user:pass@mariadb:3306/poundcake

# StackStorm (required)
POUNDCAKE_STACKSTORM_URL=http://stackstorm-api:9101
POUNDCAKE_STACKSTORM_API_KEY=<auto-generated-on-startup>
POUNDCAKE_STACKSTORM_VERIFY_SSL=False

# Application
POUNDCAKE_LOG_LEVEL=INFO
POUNDCAKE_APP_VERSION=1.0.0
```

**Oven Services (prep-chef, chef, timer):**
```bash
# API endpoint
POUNDCAKE_API_URL=http://api:8000

# Polling intervals
OVEN_INTERVAL=5          # Prep Chef poll interval (seconds)
OVEN_POLL_INTERVAL=5     # Chef poll interval (seconds)
TIMER_INTERVAL=10   # Timer poll interval (seconds)

# Logging
LOG_LEVEL=INFO
```

**Database:**
```bash
DB_USER=poundcake
DB_PASSWORD=poundcake
DB_NAME=poundcake
DB_ROOT_PASSWORD=rootpassword
```

**StackStorm:**
```bash
MONGO_PASSWORD=password
RABBITMQ_PASSWORD=password
```

### Automatic Setup

The ST2_API_KEY is automatically generated on first startup:
1. `st2client` container runs `automated-setup.sh`
2. Generates API key and saves to `config/st2_api_key`
3. API container reads key from shared volume
4. No manual configuration required!

### Creating Recipes

Recipes define multi-step workflows with ingredients (tasks):

```bash
# Create recipe with ingredients
curl -X POST http://localhost:8000/api/v1/recipes/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "HostDown",
    "description": "Remediate host down alerts",
    "enabled": true,
    "ingredients": [
      {
        "task_id": "check_host",
        "task_name": "Check Host Connectivity",
        "task_order": 1,
        "is_blocking": true,
        "st2_action": "core.local",
        "parameters": {
          "cmd": "ping -c 3 {{instance}}"
        },
        "expected_time_to_completion": 10,
        "timeout": 30,
        "retry_count": 2,
        "retry_delay": 5,
        "on_failure": "continue"
      },
      {
        "task_id": "restart_service",
        "task_name": "Restart Service",
        "task_order": 2,
        "is_blocking": true,
        "st2_action": "core.remote",
        "parameters": {
          "hosts": "{{instance}}",
          "cmd": "systemctl restart myservice"
        },
        "expected_time_to_completion": 20,
        "timeout": 60,
        "retry_count": 1,
        "retry_delay": 10,
        "on_failure": "stop"
      }
    ]
  }'
```

Recipe matching: Alert's `group_name` field matches Recipe's `name` field. By default, `group_name` is set from `labels.alertname` in the Alertmanager payload.

## API Endpoints

### Core Endpoints

- `POST /api/v1/webhook` - Receive Alertmanager webhooks (returns 202 Accepted)
- `GET /api/v1/alerts` - Query alerts with filters (processing_status, req_id, alert_name, etc.)
- `GET /api/v1/alerts/{id}` - Get specific alert
- `PUT /api/v1/alerts/{id}` - Update alert status

### Oven (Task) Management

- `POST /api/v1/ovens/bake/{alert_id}` - Create ovens from recipe ingredients
- `GET /api/v1/ovens` - List ovens with filters (processing_status, req_id, etc.)
- `PATCH /api/v1/ovens/{id}` - Update oven status
- `PUT /api/v1/ovens/{id}` - Update oven (alternative to PATCH)

### Recipe Management

- `POST /api/v1/recipes/` - Create recipe with ingredients
- `GET /api/v1/recipes/` - List all recipes
- `GET /api/v1/recipes/{id}` - Get recipe by ID (includes ingredients)
- `GET /api/v1/recipes/by-name/{recipe_name}` - Get recipe by name
- `DELETE /api/v1/recipes/{id}` - Delete recipe

### StackStorm Bridge

- `POST /api/v1/stackstorm/execute` - Execute ST2 action (proxy to StackStorm)

### Health & Monitoring

- `GET /api/v1/health` - Service health check (includes ST2 status)
- `GET /api/v1/stats` - System statistics
- `POST /api/v1/auth/login` - Create session (when auth is enabled)
- `GET /metrics` - Prometheus metrics (when enabled)

See [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md) for complete API documentation.

## Workflow

### 1. Alert Reception (pre_heat service)

```
Alertmanager sends webhook
    ↓
POST /api/v1/webhook (generates req_id)
    ↓
pre_heat creates Alert (processing_status="new")
    ↓
Return 202 Accepted immediately (< 10ms)
```

### 2. Alert Dispatching (prep-chef)

```
prep-chef polls: GET /alerts?processing_status=new
    ↓
For each alert:
  - Match alert.group_name to recipe.name
  - POST /ovens/bake/{alert_id}
  - Creates one oven per recipe ingredient
  - Updates alert (processing_status="processing")
```

### 3. Task Execution (chef)

```
chef polls: GET /ovens?processing_status=new
    ↓
For each oven (respecting is_blocking dependencies):
  - Extract ingredient.st2_action and parameters
  - POST /stackstorm/execute (via API bridge)
  - Update oven (processing_status="processing", action_id=ST2_ID)
```

### 4. Completion Monitoring (timer)

```
timer polls: GET /ovens?processing_status=processing
    ↓
For each oven:
  - GET ST2 execution status
  - When complete: PATCH /ovens/{id}
  - Update (processing_status="complete", st2_status="succeeded")
```

### 5. Execution Tracking

```sql
-- Get complete audit trail for a specific request
SELECT * FROM alerts 
WHERE req_id = 'abc-123-def-456';

SELECT * FROM ovens 
WHERE req_id = 'abc-123-def-456'
ORDER BY task_order;

-- Check current status
SELECT 
  a.alert_name,
  a.processing_status as alert_status,
  o.task_order,
  i.task_name,
  o.processing_status as oven_status,
  o.st2_status
FROM alerts a
JOIN ovens o ON a.id = o.alert_id
JOIN ingredients i ON o.ingredient_id = i.id
WHERE a.req_id = 'abc-123-def-456'
ORDER BY o.task_order;
```

## Testing

### Integration Tests

```bash
# Run all tests
./tests/run_all_tests.sh

# Webhook test only
./tests/test_webhook.sh

# End-to-end flow test
./tests/test_flow.sh
```

Expected output:
```
========================================
Test Summary
========================================
Total Tests: 2
Passed: 2
Failed: 0

[OK] All tests passed!
```

### Unit Tests (when available)

```bash
# Install test dependencies
pip install -r requirements.txt

# Run unit tests
pytest tests/

# Test specific files
pytest tests/test_api_health.py
pytest tests/test_models.py

# With coverage
pytest --cov=api tests/
```

## Documentation

- [API Endpoints](docs/API_ENDPOINTS.md) - Complete API reference
- [Architecture](docs/ARCHITECTURE.md) - System design and data flow
- [Database Migrations](docs/DATABASE_MIGRATIONS.md) - Alembic migration guide
- [Alembic Quick Reference](docs/ALEMBIC_QUICKREF.md) - Common migration commands
- [CLI Documentation](docs/CLI.md) - Command-line interface
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions

## Development

### Local Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Run migrations
python api/migrate.py upgrade

# Start development server
uvicorn api.main:app --reload

# Run tests
pytest
```

### Project Structure

```
poundcake/
├── api/                    # Application code
│   ├── api/               # Route handlers (routes.py, ovens.py, stackstorm.py)
│   ├── core/              # Core functionality (config, database, logging)
│   ├── models/            # SQLAlchemy models (Recipe, Ingredient, Alert, Oven)
│   ├── schemas/           # Pydantic schemas (request/response models)
│   ├── services/          # Business logic (pre_heat, stackstorm_service)
│   └── scripts/           # Entrypoint scripts (entrypoint-auto-migrate.sh)
├── kitchen/               # Background workers
│   ├── prep_chef.py       # Dispatcher (alerts → ovens)
│   ├── chef.py            # Executor (ovens → stackstorm)
│   └── timer.py           # Status monitor (tracks ST2 completions)
├── alembic/               # Database migrations
│   └── versions/          # Migration scripts (2026_02_03_1600_initial_schema.py)
├── docker/                # Docker configuration
│   ├── mariadb-init/      # Database initialization
│   ├── mongodb-init/      # MongoDB setup for ST2
│   └── st2-init/          # StackStorm initialization
├── scripts/               # Automation scripts
│   └── automated-setup.sh # ST2 API key generation
├── tests/                 # Test files
│   ├── test_webhook.sh    # Webhook integration test
│   └── test_flow.sh       # End-to-end flow test
│   ├── test_models.py     # Model unit tests
│   └── test_api_health.py # API health unit tests
├── examples/              # Example recipes
├── docker-compose.yml     # Full stack deployment
├── Dockerfile             # Multi-service container image
├── alembic.ini            # Alembic configuration
└── README.md
```

## Requirements

### Runtime Requirements

- Python 3.11+
- MySQL/MariaDB 10.11+
- StackStorm (with Redis and RabbitMQ)

### StackStorm Requirements

StackStorm requires:
- Redis for coordination and locking
- RabbitMQ for task distribution
- MongoDB for data storage

## Configuration Examples

### Alertmanager Configuration

```yaml
receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake.poundcake.svc:8000/api/v1/webhook
        send_resolved: true
        http_config:
          follow_redirects: true

route:
  receiver: poundcake
  group_by: ['alertname', 'instance']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
```

### StackStorm Workflow Example

```yaml
# packs/remediation/actions/workflows/host_down.yaml
version: 1.0

description: Remediate host down alerts

input:
  - alert_name
  - instance
  - req_id

tasks:
  check_host:
    action: core.remote
    input:
      hosts: <% ctx().instance %>
      cmd: "ping -c 3 <% ctx().instance %>"
    next:
      - when: <% succeeded() %>
        do: log_success
      - when: <% failed() %>
        do: restart_services

  restart_services:
    action: core.remote
    input:
      hosts: <% ctx().instance %>
      cmd: "systemctl restart myservice"
    next:
      - do: log_complete

  log_success:
    action: core.local
    input:
      cmd: "echo 'Host is up'"

  log_complete:
    action: core.local
    input:
      cmd: "echo 'Remediation complete'"
```

## Upgrading

### Database Schema Upgrades

```bash
# Backup database first
mysqldump -u poundcake -p poundcake > backup.sql

# Test on staging
python api/migrate.py upgrade

# Apply to production
python api/migrate.py upgrade
```

### Application Upgrades

```bash
# Docker Compose
docker compose pull
docker compose up -d

# Kubernetes
helm upgrade poundcake poundcake/poundcake --version <new-version>
```

## Troubleshooting

## Reading Logs

PoundCake logs are structured and include consistent fields so you can trace a request end‑to‑end.

**Key fields**
- `req_id`: Correlates a webhook through alerts → ovens → StackStorm execution
- `method`, `status_code`, `latency_ms`: HTTP diagnostics
- `alert_id`, `oven_id`, `recipe_name`: Domain identifiers for the workflow

**Follow a single alert end‑to‑end**
```bash
# 1) Find the req_id from the webhook response header
curl -i -X POST http://localhost:8000/api/v1/webhook -H "Content-Type: application/json" -d @payload.json

# 2) Tail logs and filter by req_id
docker compose logs -f api prep-chef chef timer | grep "<REQ_ID>"
```

**Service‑specific views**
```bash
# API (webhook, recipes, alerts, ovens)
docker compose logs -f api

# Prep Chef (alert → ovens)
docker compose logs -f prep-chef

# Chef (ovens → StackStorm)
docker compose logs -f chef

# Timer (execution completion)
docker compose logs -f timer
```

### Common Issues

**Issue**: Webhook returns 500 error
**Solution**: Check database connectivity and StackStorm API availability

**Issue**: Alerts not processing
**Solution**: Check alert `processing_status` and prep-chef/chef logs to ensure alerts are being baked and ovens are being executed

**Issue**: StackStorm executions failing
**Solution**: Verify Redis and RabbitMQ are running and accessible

**Issue**: Database connection errors
**Solution**: Check DATABASE_URL and network connectivity

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more solutions.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

## License

[Your License Here]

## Support

- Issues: https://github.com/yourorg/poundcake/issues
- Documentation: https://github.com/yourorg/poundcake/tree/main/docs

---

**Version:** 0.0.1
**Last Updated:** January 23, 2026

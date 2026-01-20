# PoundCake

An extensible auto-remediation framework that bridges Prometheus Alertmanager with StackStorm. PoundCake receives alerts from Alertmanager and automatically executes remediation actions through StackStorm.

## Features

- **Webhook Receiver**: Receives alerts from Prometheus Alertmanager with unique request_id tracking
- **StackStorm Integration**: Executes remediation actions via StackStorm API
- **Prometheus Rule Management**: Edit and manage Prometheus alert rules via CRDs and GitOps
- **PromQL Query Builder**: Visual builder with Basic, Advanced, and Raw modes
- **Management UI**: Web interface with Dashboard, Alert Status, Mappings, and more
- **Database-Backed Mappings**: Alert-to-action mappings stored in MySQL/MariaDB
- **Async Processing**: Celery + Redis for background task processing
- **Authentication**: Optional session-based authentication with Kubernetes secret integration
- **Command-Line Interface**: Powerful CLI (`pcake`) for managing alerts and rules
- **Complete Audit Trail**: Track from alert to workflow to execution with request_id
- **Prometheus Metrics**: Built-in metrics at `/metrics` endpoint
- **Horizontal Scaling**: Distributed locking with Redis for multi-instance deployments

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌─────────────┐
│ Alertmanager│────▶│           PoundCake                 │────▶│  StackStorm │
│             │     │  ┌─────────┐  ┌─────────┐           │     │     API     │
└─────────────┘     │  │ FastAPI │  │  Celery │           │     └─────────────┘
                    │  │  (API)  │  │ Workers │           │            │
                    │  └────┬────┘  └────┬────┘           │            ▼
                    │       │            │                │     ┌─────────────┐
                    │  ┌────┴────┐       │                │     │   Target    │
                    │  │   UI    │       │                │     │   Systems   │
                    │  │ (nginx) │       │                │     └─────────────┘
                    │  └─────────┘       │                │
                    │       ▼            ▼                │
                    │  ┌─────────┐  ┌─────────┐           │
                    │  │  MySQL  │  │  Redis  │           │
                    │  │MariaDB  │  │ (broker)│           │
                    │  └─────────┘  └─────────┘           │
                    └─────────────────────────────────────┘
```

### Containers

The application consists of separate containers, each built and published independently via GitHub workflows:

| Container | Image | Description |
|-----------|-------|-------------|
| API | `ghcr.io/aedan/poundcake` | FastAPI backend |
| UI | `ghcr.io/aedan/poundcake-ui` | Nginx-served frontend |
| Celery | `ghcr.io/aedan/poundcake` | Background task workers (same image as API) |

## Quick Start

### Prerequisites

- Kubernetes cluster
- Helm 3.x
- StackStorm instance (can be deployed via Helm)
- MySQL/MariaDB database
- Redis (can be deployed with chart)

### 1. Install StackStorm

PoundCake requires a running StackStorm instance. Use the provided install script:

```bash
cd bin
./install-stackstorm.sh
```

### 2. Install PoundCake

```bash
# Install from OCI registry
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake" \
  --set stackstorm.url=http://stackstorm-st2api.stackstorm.svc.cluster.local:9101 \
  --set stackstorm.apiKey=your-st2-api-key

# Or install from local chart (for development)
helm install poundcake ./helm/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake" \
  --set stackstorm.apiKey=your-st2-api-key
```

### 3. Configure Alertmanager

Add PoundCake as a webhook receiver:

```yaml
receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake.poundcake.svc.cluster.local:8080/api/v1/webhook
        send_resolved: true
```

## Database Schema

PoundCake uses MySQL/MariaDB for persistent storage:

### poundcake_api_calls
Tracks all webhook requests with unique request_id
```sql
id, request_id (unique), method, path, headers, body,
status_code, created_at, completed_at
```

### poundcake_alerts
Stores Alertmanager alert data
```sql
id, api_call_id, fingerprint, alert_name, severity,
instance, labels, annotations, processing_status, created_at
```

### poundcake_st2_execution_link
Links PoundCake requests to StackStorm executions
```sql
id, request_id, alert_id, st2_execution_id,
st2_rule_ref, st2_action_ref, created_at
```

### poundcake_mappings
Database-backed alert-to-action mappings
```sql
id, alert_name, handler, config (JSON), description,
enabled, created_at, updated_at
```

## API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/webhook` | POST | Receive Alertmanager webhooks |
| `/api/v1/status/{request_id}` | GET | Get status including ST2 executions |
| `/api/v1/alerts` | GET | List alerts |
| `/api/v1/health` | GET | Health check |
| `/api/v1/ready` | GET | Readiness check |

### Mappings API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mappings` | GET | List all mappings |
| `/api/mappings/{alert_name}` | GET | Get specific mapping |
| `/api/mappings` | POST | Create mapping |
| `/api/mappings/{alert_name}` | PUT | Update mapping |
| `/api/mappings/{alert_name}` | DELETE | Delete mapping |
| `/api/mappings/export` | GET | Export mappings as YAML |
| `/api/mappings/import` | POST | Import mappings from YAML |

### StackStorm API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stackstorm/packs` | GET | List available packs |
| `/api/stackstorm/actions` | GET | List actions |
| `/api/stackstorm/actions/{ref}` | GET | Get action details |
| `/api/stackstorm/executions` | GET | List executions |

### Prometheus API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/prometheus/rules` | GET | List alert rules |
| `/api/prometheus/metrics` | GET | List available metrics |
| `/api/prometheus/labels` | GET | List label names |
| `/api/prometheus/label-values/{name}` | GET | List label values |
| `/api/prometheus/health` | GET | Prometheus health check |

### Legacy Endpoints (UI Compatibility)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/alerts` | GET | List alerts (UI format) |
| `/alerts/stats` | GET | Alert statistics |
| `/alerts/{fingerprint}` | GET | Alert details |
| `/remediations` | GET | Remediation history |
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/metrics` | GET | Prometheus metrics |

## Management UI

The web UI is deployed as a separate container (`ghcr.io/aedan/poundcake-ui`) and communicates with the API service.

### UI Tabs

1. **Dashboard** - System status, health indicators, recent activity
2. **Alert Status** - Real-time alert tracking with filtering
3. **Prometheus Rules** - View/edit rules with PromQL Query Builder
4. **Mappings** - Create and edit alert-to-action mappings
5. **StackStorm Actions** - Browse available actions by pack
6. **Execution History** - View past remediations
7. **Health** - Component health checks

### Accessing the UI

```bash
# Port forward the UI service
kubectl port-forward svc/poundcake-ui 8080:80 -n poundcake

# Open in browser
open http://localhost:8080
```

The UI connects to the API service automatically within the cluster.

## Command-Line Interface (CLI)

```bash
# Configure API endpoint
export POUNDCAKE_URL=http://poundcake.example.com:8080

# List alerts
pcake alerts list
pcake alerts list --status remediating

# Watch alerts in real-time
pcake alerts watch --watch

# Manage Prometheus rules
pcake rules list
pcake rules create my-alerts app-alerts HighMemory \
  --expr 'memory_usage > 90' \
  --for 5m \
  --severity critical

# Output formats
pcake --format json alerts list
pcake --format yaml rules get my-alerts app-alerts HighMemory
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POUNDCAKE_DATABASE_URL` | MySQL connection URL | Required |
| `POUNDCAKE_CELERY_BROKER_URL` | Redis broker URL | `redis://localhost:6379/0` |
| `POUNDCAKE_STACKSTORM_URL` | StackStorm API URL | Required |
| `POUNDCAKE_STACKSTORM_API_KEY` | StackStorm API key | Required |
| `POUNDCAKE_PROMETHEUS_URL` | Prometheus API URL | `http://localhost:9090` |
| `POUNDCAKE_AUTH_ENABLED` | Enable authentication | `false` |
| `POUNDCAKE_METRICS_ENABLED` | Enable /metrics endpoint | `true` |
| `POUNDCAKE_LOG_LEVEL` | Logging level | `INFO` |

### Helm Values

See [helm/poundcake/values.yaml](helm/poundcake/values.yaml) for all configuration options.

Key sections:
- `database` - MySQL/MariaDB connection settings
- `redis` - Redis for Celery broker
- `stackstorm` - StackStorm connection and authentication
- `prometheus` - Prometheus integration and CRD settings
- `auth` - Authentication configuration
- `git` - GitOps integration for rule management

## Horizontal Scaling

For production deployments with multiple replicas:

```bash
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set replicaCount=3 \
  --set redis.enabled=true \
  --set redis.password=my-redis-password \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake"
```

## Authentication

Enable authentication to protect the UI and API:

```bash
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --set auth.enabled=true

# Retrieve the generated admin password
kubectl get secret poundcake-admin -n poundcake \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

## Documentation

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Complete architecture guide
- **[STACKSTORM_INTEGRATION.md](docs/STACKSTORM_INTEGRATION.md)** - ST2 integration details
- **[INSTALL.md](docs/INSTALL.md)** - Detailed installation guide
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues
- **[SAMPLE_PAYLOADS.md](docs/SAMPLE_PAYLOADS.md)** - Example webhooks

## Prometheus Metrics

Available at `/metrics`:

- `poundcake_alerts_received_total` - Total alerts received
- `poundcake_alerts_processed_total` - Total alerts processed
- `poundcake_remediations_executed_total` - Total remediations executed
- `poundcake_remediation_duration_seconds` - Remediation duration histogram
- `poundcake_st2_executions_total` - StackStorm executions
- `poundcake_http_requests_total` - HTTP request counts
- `poundcake_active_tasks` - Currently processing tasks

## License

MIT

## Support

- GitHub: https://github.com/aedan/poundcake
- Documentation: See `docs/` directory

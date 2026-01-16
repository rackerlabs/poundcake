=======
# PoundCake - Complete Alertmanager Integration

**A lightweight tracking layer for Alertmanager webhooks with StackStorm integration**

This unified repository combines the containerized API backend with CLI management tools and a web UI for complete alert remediation management.

## What's Included

- **API Backend**: Fully containerized FastAPI application with Celery workers
- **CLI Tool**: `pcake` command-line interface for managing alerts and rules
- **Web UI**: Management interface for monitoring and configuration
- **StackStorm Integration**: Complete workflow automation in containers

## Architecture

```
Alert → PoundCake API (container) → Celery (container) → StackStorm (container) → Remediation
          ↓                                                ↓
      MariaDB (container - shared database)
          ↑
      Web UI (container :8080)
          ↑
      CLI Tool (pcake)
```

### Container Stack

**Infrastructure:**
- MariaDB (shared by PoundCake and StackStorm)
- Redis (Celery broker)
- RabbitMQ (StackStorm message broker)

**StackStorm Services (7 containers):**
- st2api, st2auth, st2stream
- st2rulesengine, st2actionrunner
- st2scheduler, st2notifier

**PoundCake Services:**
- API (FastAPI webhook receiver) - Port 8000
- Celery workers (Background processing)
- Flower (Celery monitoring) - Port 5555
- Web UI (Management interface) - Port 8080

## Features

### Core API Features
- Unique request_id for every webhook
- Complete audit trail from alert to execution
- Simple 3-table database design
- Async processing with Celery
- Cross-system queries with StackStorm

### CLI Features (`pcake` command)
- List and filter alerts by status
- Watch alerts in real-time
- Manage Prometheus rules
- Create and update alert configurations
- Query alert history and execution status

### Web UI Features
- Dashboard with alert overview
- Real-time status monitoring
- Alert history browser
- Configuration management
- Health monitoring

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd poundcake-merged

# Option A: Automated setup (recommended)
./scripts/setup.sh

# Option B: Manual setup
docker-compose up -d
pip install -e .
```

The automated setup script will:
- Build and start all containers
- Wait for services to be healthy
- Create StackStorm API key
- Install CLI tool
- Run integration tests

### 2. Access Services

- **Web UI**: http://localhost:8080
- **API Documentation**: http://localhost:8000/docs
- **Flower (Celery monitoring)**: http://localhost:5555
- **RabbitMQ Management**: http://localhost:15672 (stackstorm/stackstorm)

### 3. Configure Alertmanager

Add PoundCake as a webhook receiver:

```yaml
# alertmanager.yml
route:
  receiver: poundcake
  group_by: ['alertname', 'instance']

receivers:
  - name: poundcake
    webhook_configs:
      - url: http://localhost:8000/api/v1/webhook
        send_resolved: true
```

### 4. Test the Webhook

**Use sample payloads:**

```bash
# Quick test
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/test-basic.json

# Test firing alert
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/alert-firing.json

# See all examples
ls examples/*.json
```

**Or use the test script:**

```bash
./scripts/test-webhook.sh
```

See `examples/README.md` for more test scenarios and payload customization.

## Testing

### Sample Payloads

The `examples/` directory contains ready-to-use webhook payloads:

| File | Description | Use Case |
|------|-------------|----------|
| `test-basic.json` | Simple test alert | Quick smoke test |
| `alert-firing.json` | Realistic firing alert | Test alert processing |
| `alert-resolved.json` | Resolved alert | Test alert clearing |
| `alert-multiple.json` | 3 alerts in one webhook | Test batch processing |
| `alert-critical.json` | Critical severity alert | Test urgent workflows |

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/test-basic.json
```

### Verify Results

```bash
# Check API response (should return request_id)
# Check stored alerts
curl http://localhost:8000/api/v1/alerts

# Check task status
curl http://localhost:8000/api/v1/requests/{request_id}/status

# View in Flower
open http://localhost:5555
```

### Test Script

Automated testing with health checks:
```bash
./scripts/test-webhook.sh
```

## Using the CLI

### Configuration

```bash
# Set API endpoint
export POUNDCAKE_URL=http://localhost:8000

# Optional: Set API key if authentication is enabled
export POUNDCAKE_API_KEY=your-api-key
```

### Common Commands

```bash
# List all alerts
pcake alerts list

# Filter alerts by status
pcake alerts list --status remediating

# Watch alerts in real-time
pcake alerts watch

# Get alert details
pcake alerts get <alert-id>

# List Prometheus rules
pcake rules list

# Create a new rule
pcake rules create namespace name rule-name \
  --expr 'metric > threshold' \
  --severity warning \
  --summary "Alert description"
```

### CLI Help

```bash
# General help
pcake --help

# Command-specific help
pcake alerts --help
pcake rules --help
```

## Using the Web UI

1. Navigate to http://localhost:8080
2. View the dashboard for alert overview
3. Browse alert history and status
4. Configure alert mappings and handlers
5. Monitor system health

## Database Schema

PoundCake uses a simple 4-table design:

1. **poundcake_api_calls**: Request tracking with unique request_id
2. **poundcake_alerts**: Alert data and status
3. **poundcake_st2_execution_link**: Links to StackStorm executions
4. **poundcake_task_results**: Celery task execution tracking linked to request_id

Additionally, Celery creates its own tables for result backend:
- **celery_taskmeta**: Native Celery task metadata
- **celery_tasksetmeta**: Native Celery task set metadata

## Development

### Project Structure

```
poundcake-merged/
├── src/
│   ├── api/                 # API backend (FastAPI)
│   │   ├── api/            # API endpoints
│   │   ├── models/         # Database models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── tasks/          # Celery tasks
│   │   └── main.py         # FastAPI application
│   ├── cli/                # CLI tool
│   │   ├── commands/       # CLI commands
│   │   ├── client.py       # API client
│   │   └── main.py         # CLI entry point
│   └── ui/                 # Web UI
│       ├── static/         # HTML/CSS/JS
│       ├── nginx/          # Nginx config
│       └── Dockerfile      # UI container
├── docker-compose.yml      # Complete stack
├── pyproject.toml          # Python dependencies
└── README.md              # This file
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src tests/
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type checking
mypy src/
```

## API Endpoints

### Webhook Endpoint

```bash
POST /api/v1/webhook
Content-Type: application/json

{
  "alerts": [...],
  "groupLabels": {...},
  "commonAnnotations": {...}
}
```

### Query Endpoints

```bash
# Get all API calls
GET /api/calls

# Get specific call
GET /api/calls/{request_id}

# Get alerts
GET /api/alerts

# Get ST2 execution links
GET /api/st2/executions

# Get task status by task_id
GET /api/tasks/{task_id}

# Get all tasks for a request_id
GET /api/requests/{request_id}/tasks

# Get complete request status (API call, alerts, tasks, ST2 executions)
GET /api/requests/{request_id}/status
```

## Configuration

### Environment Variables

**API Configuration:**
- `DATABASE_URL`: Database connection string
- `CELERY_BROKER_URL`: Redis URL for Celery
- `ST2_API_URL`: StackStorm API endpoint
- `ST2_API_KEY`: StackStorm API key (optional)
- `LOG_LEVEL`: Logging level (default: INFO)

**CLI Configuration:**
- `POUNDCAKE_URL`: API endpoint URL
- `POUNDCAKE_API_KEY`: API key for authentication

**UI Configuration:**
- `API_URL`: Backend API URL (default: http://api:8000)

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Check all services
docker-compose ps
```

### Logs

```bash
# API logs
docker-compose logs -f api

# Celery logs
docker-compose logs -f celery

# All logs
docker-compose logs -f
```

### Metrics

PoundCake exposes Prometheus metrics at `/metrics` endpoint.

## Troubleshooting

### Container Issues

```bash
# Restart specific service
docker-compose restart api

# Rebuild and restart
docker-compose up -d --build api

# View detailed logs
docker-compose logs --tail=100 api
```

### Database Issues

```bash
# Access database
docker-compose exec mariadb mysql -uroot -prootpassword

# Check tables
USE poundcake;
SHOW TABLES;

# View recent calls
SELECT * FROM poundcake_api_calls ORDER BY created_at DESC LIMIT 10;
```

### CLI Issues

```bash
# Verify API connectivity
curl http://localhost:8000/health

# Check CLI configuration
echo $POUNDCAKE_URL

# Use verbose output
pcake -v alerts list
```

## Migration from Standalone Repos

If you're migrating from the standalone `poundcake-api` or `poundCake` repositories:

1. The API structure remains unchanged in `src/app/`
2. CLI is now in `src/poundcake_cli/` with the same commands
3. UI is in `src/poundcake_ui/` and accessible at port 8080
4. All dependencies are consolidated in `pyproject.toml`
5. Docker Compose includes all services in one stack

## Version History

- **v1.3.0**: Merged repository with API, CLI, and UI
  - Unified docker-compose stack
  - Consolidated dependencies
  - Integrated CLI and UI with API backend

- **v1.2.0** (API): Fully containerized architecture
  - 13-container stack
  - Simplified 3-table database
  - Complete StackStorm integration

- **v0.5.0** (Original): CLI and UI features
  - Command-line management
  - Web interface
  - Kubernetes deployment support

## Contributing

This is a merged repository combining:
- API backend from `brewc/poundcake-api`
- CLI and UI from `aedan/poundCake`

Contributions should maintain compatibility with all three components.

## License

MIT License

## Authors

- Chris Breu (API Backend)
- Jake Briggs (CLI and UI)

## Support

For issues, questions, or contributions, please open an issue on the repository.

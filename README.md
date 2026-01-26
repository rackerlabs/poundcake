# PoundCake

Auto-remediation framework that bridges Prometheus Alertmanager with StackStorm.

## Overview

PoundCake receives alerts from Prometheus Alertmanager and automatically executes remediation workflows through StackStorm. It provides fast webhook response, complete audit trails, and stateless design for horizontal scaling.

## Architecture

```
Alertmanager --> PoundCake API --> StackStorm --> Target Systems
                      |
                   Database
```

### Components

- **FastAPI Application**: Webhook receiver with background processing
- **Database (MySQL/MariaDB)**: Stores recipes, alerts, and execution tracking
- **StackStorm**: Executes remediation workflows
- **Redis**: Required for StackStorm coordination
- **RabbitMQ**: Required for StackStorm task distribution

## Quick Start

### Docker Compose

```bash
# Clone repository
git clone https://github.com/yourorg/poundcake.git
cd poundcake

# Start all services
docker-compose up -d

# Check health
curl http://localhost:8000/api/v1/health
```

Services:
- PoundCake API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- RabbitMQ Management: http://localhost:15672 (stackstorm/stackstorm)

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

## Features

- **Fast Response**: Webhook returns 202 immediately, processes in background
- **Database Migrations**: Alembic-powered schema management for safe upgrades
- **Complete Audit Trail**: Track alerts from webhook to execution via req_id
- **Stateless Design**: No Redis/Celery dependency for PoundCake, scales horizontally
- **Recipe Matching**: Flexible alert-to-workflow mapping with patterns and defaults
- **Health Checks**: Built-in endpoints for Kubernetes liveness/readiness probes
- **Prometheus Metrics**: Metrics endpoint at `/metrics`
- **API Documentation**: Interactive docs at `/docs`

## Database Setup

PoundCake uses Alembic for database schema management.

```bash
# Run migrations (creates all tables)
python scripts/migrate.py upgrade

# Check current version
python scripts/migrate.py current

# Create new migration
python scripts/migrate.py create "description"
```

See [docs/DATABASE_MIGRATIONS.md](docs/DATABASE_MIGRATIONS.md) for details.

## Configuration

### Environment Variables

```bash
# Database (required)
DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname

# StackStorm (required)
ST2_API_URL=http://st2api:9101/v1
ST2_API_KEY=your-api-key

# Application
LOG_LEVEL=INFO
DEBUG=false
```

### Creating Recipes

Recipes map alerts to StackStorm workflows:

```bash
# Create recipe
curl -X POST http://localhost:8000/api/recipes/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "HostDown",
    "description": "Remediate host down alerts",
    "st2_workflow_ref": "remediation.host_down_workflow"
  }'
```

## API Endpoints

### Core Endpoints

- `POST /api/v1/webhook` - Receive Alertmanager webhooks
- `GET /api/v1/alerts` - Query alerts with filters
- `POST /api/v1/alerts/process` - Execute recipes for alerts
- `GET /api/v1/executions/{req_id}` - Get execution history

### Recipe Management

- `POST /api/recipes/` - Create recipe
- `GET /api/recipes/` - List recipes
- `GET /api/recipes/{id}` - Get recipe by ID
- `PUT /api/recipes/{id}` - Update recipe
- `DELETE /api/recipes/{id}` - Delete recipe

### Health & Stats

- `GET /api/v1/health` - Health check
- `GET /api/v1/health/ready` - Kubernetes readiness
- `GET /api/v1/health/live` - Kubernetes liveness
- `GET /api/v1/stats` - System statistics
- `GET /metrics` - Prometheus metrics

See [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md) for complete API documentation.

## Workflow

### 1. Alert Reception

```
Alertmanager sends webhook
    |
PreHeatMiddleware generates req_id
    |
Return 202 Accepted immediately (under 10ms)
    |
Background task processes alert
```

### 2. Alert Processing

```
POST /api/v1/alerts/process
    |
Query alerts WHERE processing_status = "new"
    |
For each alert:
  - Match to recipe (exact, pattern, or default)
  - Create oven (execution tracking)
  - Call StackStorm API
  - Store execution ID
```

### 3. Execution Tracking

```sql
-- Get complete audit trail
SELECT * FROM poundcake_alerts 
WHERE req_id = 'abc-123';

SELECT * FROM poundcake_ovens 
WHERE req_id = 'abc-123';
```

## Testing

```bash
# Run tests
pytest tests/

# Test specific file
pytest tests/test_api.py

# With coverage
pytest --cov=api tests/
```

## Documentation

- [API Endpoints](docs/API_ENDPOINTS.md) - Complete API reference
- [Architecture](docs/ARCHITECTURE.md) - System design and data flow
- [Database Migrations](docs/DATABASE_MIGRATIONS.md) - Alembic migration guide
- [Alembic Quick Reference](docs/ALEMBIC_QUICKREF.md) - Common migration commands
- [CLI Documentation](docs/CLI.md) - Command-line interface
- [StackStorm Integration](docs/STACKSTORM_INTEGRATION.md) - Integration details
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions

## Development

### Local Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Run migrations
python scripts/migrate.py upgrade

# Start development server
uvicorn api.main:app --reload

# Run tests
pytest
```

### Project Structure

```
poundcake/
├── api/                    # Application code
│   ├── api/               # Route handlers
│   ├── core/              # Core functionality (config, database, logging)
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   └── services/          # Business logic
├── alembic/               # Database migrations
│   └── versions/          # Migration scripts
├── docs/                  # Documentation
├── helm/                  # Helm chart
│   └── poundcake/
├── scripts/               # Management scripts
├── tests/                 # Test files
├── docker-compose.yml     # Docker Compose configuration
├── Dockerfile             # Container image
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
- MySQL/MariaDB for data storage

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
python scripts/migrate.py upgrade

# Apply to production
python scripts/migrate.py upgrade
```

### Application Upgrades

```bash
# Docker Compose
docker-compose pull
docker-compose up -d

# Kubernetes
helm upgrade poundcake poundcake/poundcake --version <new-version>
```

## Troubleshooting

### Common Issues

**Issue**: Webhook returns 500 error
**Solution**: Check database connectivity and StackStorm API availability

**Issue**: Alerts not processing
**Solution**: Call `POST /api/v1/alerts/process` or check processing_status

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

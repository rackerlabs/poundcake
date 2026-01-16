# Getting Started with PoundCake

Welcome! This guide will get you up and running with PoundCake in under 10 minutes.

## What is PoundCake?

PoundCake is a webhook receiver and tracking layer for Prometheus Alertmanager that:
- Receives alerts from Alertmanager
- Tracks them with unique IDs
- Triggers automated remediation via StackStorm
- Provides CLI and Web UI for management

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Git

## Quick Install

### Option 1: Automated Setup (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd poundcake-merged

# Run setup script
./setup.sh
```

The script will:
1. Start all containers
2. Install the CLI tool
3. Configure your environment
4. Test the installation

### Option 2: Manual Setup

```bash
# Clone the repository
git clone <repository-url>
cd poundcake-merged

# Start all containers
docker-compose up -d

# Install CLI
pip install -e .

# Set environment variable
export POUNDCAKE_URL=http://localhost:8000
```

## Verify Installation

### 1. Check Containers

```bash
docker-compose ps
```

You should see 14 containers running:
- mariadb, redis, rabbitmq (infrastructure)
- 7 StackStorm containers
- api, celery, flower, ui (PoundCake)

### 2. Test the API

```bash
curl http://localhost:8000/health
```

Should return: `{"status":"healthy"}`

### 3. Test the CLI

```bash
pcake --help
```

Should show CLI commands.

### 4. Access the Web UI

Open browser to: http://localhost:8080

## Your First Alert

### 1. Send a Test Alert

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "TestAlert",
          "severity": "warning"
        },
        "annotations": {
          "summary": "This is a test alert"
        }
      }
    ]
  }'
```

### 2. View the Alert

**Using CLI:**
```bash
pcake alerts list
```

**Using Web UI:**
- Navigate to http://localhost:8080
- Click on "Alerts" in the menu
- See your test alert

**Using API:**
```bash
curl http://localhost:8000/api/alerts
```

## Configure Alertmanager

Add PoundCake to your Alertmanager config:

```yaml
# alertmanager.yml
route:
  receiver: 'poundcake'

receivers:
  - name: 'poundcake'
    webhook_configs:
      - url: 'http://localhost:8000/webhook'
        send_resolved: true
```

Reload Alertmanager:
```bash
killall -HUP alertmanager
```

## Common Tasks

### Watch Alerts in Real-Time

```bash
pcake alerts watch
```

### View Alert Details

```bash
# List all alerts
pcake alerts list

# Get specific alert
pcake alerts get <alert-id>

# Filter by status
pcake alerts list --status firing
```

### Check System Health

```bash
# API health
curl http://localhost:8000/health

# View logs
docker-compose logs -f api

# Monitor Celery tasks
open http://localhost:5555
```

## Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| Web UI | http://localhost:8080 | Management interface |
| API | http://localhost:8000 | Webhook receiver |
| API Docs | http://localhost:8000/docs | Interactive API docs |
| Flower | http://localhost:5555 | Celery task monitoring |
| RabbitMQ | http://localhost:15672 | Message broker UI |

**Credentials:**
- RabbitMQ: `stackstorm` / `stackstorm`
- Default: No authentication for API/UI

## Next Steps

### 1. Configure StackStorm Workflows

Create StackStorm actions to remediate alerts:

```bash
# SSH into st2 container
docker-compose exec st2api bash

# Create a pack
st2 pack create my_remediations

# Define actions in your pack
```

### 2. Create Alert Rules

```bash
# Create a new Prometheus alert rule
pcake rules create monitoring app HighCPU \
  --expr 'rate(cpu_usage[5m]) > 0.8' \
  --severity critical \
  --summary "High CPU usage detected"
```

### 3. Set Up Monitoring

Add Prometheus to scrape PoundCake metrics:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'poundcake'
    static_configs:
      - targets: ['localhost:8000']
```

### 4. Explore the Documentation

- [API Architecture](docs/ARCHITECTURE.md)
- [CLI Guide](docs/CLI_GUIDE.md)
- [Docker Installation](docs/DOCKER_INSTALL.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Sample Payloads](docs/SAMPLE_PAYLOADS.md)

## Troubleshooting

### Containers Won't Start

```bash
# Check logs
docker-compose logs

# Restart specific service
docker-compose restart api

# Full restart
docker-compose down
docker-compose up -d
```

### CLI Not Working

```bash
# Verify installation
pip list | grep poundcake

# Reinstall
pip install -e . --force-reinstall

# Check environment
echo $POUNDCAKE_URL
```

### Can't Connect to API

```bash
# Check if API is running
curl http://localhost:8000/health

# Check API logs
docker-compose logs api

# Verify port isn't in use
netstat -tuln | grep 8000
```

### Database Issues

```bash
# Access database
docker-compose exec mariadb mysql -uroot -prootpassword

# Check tables
USE poundcake;
SHOW TABLES;
```

## Development Mode

### Enable Hot Reload

The API already has hot reload enabled. Edit files in `src/app/` and changes will auto-reload.

### Run Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src tests/
```

### Format Code

```bash
# Format
black src/ tests/

# Lint
ruff check src/ tests/
```

## Production Deployment

For production use:

1. **Security**: Add authentication, HTTPS, API keys
2. **Monitoring**: Set up Prometheus + Grafana
3. **Backups**: Regular database backups
4. **Scaling**: Use multiple Celery workers
5. **High Availability**: Deploy on Kubernetes (Helm chart coming)

See [DOCKER_INSTALL.md](docs/DOCKER_INSTALL.md) for production recommendations.

## Getting Help

- **Documentation**: Check the `docs/` folder
- **Logs**: `docker-compose logs -f`
- **API Docs**: http://localhost:8000/docs
- **Issues**: Open an issue on GitHub

## Common Patterns

### Daily Operations

```bash
# Morning check
docker-compose ps
pcake alerts list --status firing

# Monitor during the day
pcake alerts watch

# Evening review
pcake alerts list --since "today" --format json > daily_report.json
```

### Incident Response

```bash
# See current critical alerts
pcake alerts list --label "severity=critical" --status firing

# Watch in real-time
pcake alerts watch --status firing

# Get full details
pcake alerts get <alert-id> --full
```

### Maintenance

```bash
# Weekly restart
docker-compose restart

# Monthly cleanup
docker-compose down
docker volume prune
docker-compose up -d

# Database backup
docker-compose exec mariadb mysqldump -uroot -prootpassword poundcake > backup.sql
```

## What's Next?

Now that you have PoundCake running:

1. Configure your Alertmanager to send alerts
2. Create StackStorm workflows for remediation
3. Set up monitoring dashboards
4. Define alert rules for your infrastructure
5. Explore the CLI features
6. Customize the Web UI

## Summary

You should now have:
- ✓ All containers running
- ✓ CLI tool installed
- ✓ Web UI accessible
- ✓ API receiving webhooks
- ✓ Test alert sent and tracked

**Happy alerting!**

# PoundCake Scripts

This directory contains all shell scripts for PoundCake setup, testing, and management.

## Quick Start Scripts

### quickstart.sh (RECOMMENDED)
**Complete containerized setup with StackStorm**

Starts all 13 containers:
- 7 StackStorm services
- 3 PoundCake services  
- 3 infrastructure services

```bash
chmod +x scripts/quickstart.sh
./scripts/quickstart.sh
```

**What it does:**
1. Checks prerequisites (Docker, Docker Compose)
2. Configures environment
3. Builds Docker images
4. Starts all services
5. Initializes databases
6. Creates ST2 API key
7. Tests integration

**Requirements:**
- Docker 20.10+
- Docker Compose 2.0+
- 4 GB RAM minimum

---

## Testing Scripts

### test-webhook.sh
**Send test alerts to PoundCake API**

Tests the webhook endpoint with sample Alertmanager payloads.

```bash
chmod +x scripts/test-webhook.sh
./scripts/test-webhook.sh
```

Sends various test alerts:
- Firing alerts
- Resolved alerts
- Multiple alerts in batch
- Different severity levels

**Prerequisites:**
- PoundCake API must be running
- Default: http://localhost:8000

---

## Utility Scripts

### fix.sh
**Quick fixes and common operations**

Utility script for common maintenance tasks.

```bash
chmod +x scripts/fix.sh
./scripts/fix.sh
```

---

## Script Permissions

Make scripts executable:

```bash
# Make all scripts executable
chmod +x scripts/*.sh

# Or individually
chmod +x scripts/quickstart.sh
chmod +x scripts/test-webhook.sh
```

---

## Recommended Setup Flow

1. **First time setup:**
   ```bash
   ./scripts/quickstart.sh
   ```

2. **Test integration:**
   ```bash
   ./scripts/test-webhook.sh
   ```

3. **Check services:**
   ```bash
   docker-compose ps
   docker-compose logs -f
   ```

---

## Service Access After Quickstart

After running `quickstart.sh`, access:

- **PoundCake API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Flower (Celery)**: http://localhost:5555
- **RabbitMQ UI**: http://localhost:15672
- **StackStorm API**: http://localhost:9101

---

## Troubleshooting

If quickstart fails:

1. **Check Docker is running:**
   ```bash
   docker ps
   ```

2. **Check logs:**
   ```bash
   docker-compose logs -f
   ```

3. **Restart services:**
   ```bash
   docker-compose restart
   ```

4. **Clean restart:**
   ```bash
   docker-compose down -v
   ./scripts/quickstart.sh
   ```

---

## Notes

- All scripts use bash (`#!/bin/bash`)
- Scripts should be run from project root
- Environment variables can be set in `.env`
- Logs are written to `./logs/`

---

## Contributing

When adding new scripts:
1. Place them in this `scripts/` directory
2. Make them executable (`chmod +x`)
3. Add documentation to this README
4. Use descriptive names
5. Include error handling

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

## Development Scripts

### setup-dev-env.sh
**Set up local development environment**

Creates a Python virtualenv with all development dependencies for local testing.

```bash
./scripts/setup-dev-env.sh
```

**What it does:**
1. Checks Python 3.11+ is installed
2. Creates virtualenv at `./venv/`
3. Installs all runtime dependencies
4. Installs all dev dependencies (pytest, black, ruff, mypy)
5. Installs package in editable mode

**Use this when:**
- Setting up local development for the first time
- Dependencies have been updated
- Your virtualenv is broken/corrupted

---

### test-local.sh
**Run all pre-push tests locally**

Runs the same checks that GitHub Actions runs on push to prevent CI failures.

```bash
./scripts/test-local.sh
```

**What it tests:**
1. Ruff linting (`ruff check api tests`)
2. Black formatting (`black --check api tests`)
3. MyPy type checking (`mypy api`)
4. Pytest with coverage (`pytest tests/ -v --cov=api`)

**Tip:** Always run this before `git push` to catch issues early!

**Quick fixes if tests fail:**
```bash
source venv/bin/activate
black api tests              # Auto-format code
ruff check --fix api tests   # Auto-fix linting issues
./scripts/test-local.sh      # Test again
```

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

### For Docker/Production Testing:

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

### For Local Development:

1. **Setup dev environment:**
   ```bash
   ./scripts/setup-dev-env.sh
   source venv/bin/activate
   ```

2. **Make your changes:**
   ```bash
   # Edit code...
   vim api/...
   ```

3. **Test before pushing:**
   ```bash
   ./scripts/test-local.sh
   ```

4. **Fix issues if needed:**
   ```bash
   black api tests
   ruff check --fix api tests
   ./scripts/test-local.sh
   ```

5. **Commit and push:**
   ```bash
   git add .
   git commit -m "your changes"
   git push
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

# Scripts Directory

This directory contains helper scripts for managing and deploying PoundCake.

## Scripts

### quickstart.sh

**Purpose:** Automated full deployment script
**Usage:**

```bash
./scripts/quickstart.sh
```

**What it does:**

1. Checks prerequisites (Docker, Docker Compose)
2. Creates .env configuration file
3. Starts all services with docker compose
4. Waits for services to initialize
5. Verifies deployment

This is the easiest way to get PoundCake up and running.

### automated-setup.sh

**Purpose:** Automatic StackStorm API key generation (runs in st2client container)
**Used by:** Docker Compose automatically

**What it does:**

1. Waits for StackStorm services to be responsive
2. Authenticates with StackStorm using default credentials
3. Generates a new API key
4. Writes key to `/app/config/st2_api_key` (runtime config)
5. Updates `.env` file as reference

**You don't need to run this manually!** It's executed automatically by the `st2client` container when you run `docker compose up -d`.

## Script Conventions

### Naming

- Bash scripts: `.sh` extension
- Python scripts: `.py` extension
- Use lowercase with hyphens for bash scripts: `automated-setup.sh`
- Use lowercase with underscores for Python scripts: `init_database.py`

### Location

This directory should contain **only** helper scripts that:

- Assist with deployment and configuration
- Perform administrative tasks
- Are not part of the core application

### What NOT to Put Here

- Service code (goes in `api/`, `oven/`, `timer/`)
- Application logic (goes in appropriate service directory)
- Configuration files (goes in `config/` or `docker/`)
- Tests (goes in `tests/`)

## Creating New Scripts

When creating a new helper script:

1. **Add executable permissions:**

   ```bash
   chmod +x scripts/your-script.sh
   ```

2. **Add shebang line:**

   ```bash
   #!/bin/bash
   ```

   or

   ```python
   #!/usr/bin/env python3
   ```

3. **Add documentation:**
   - Update this README
   - Add help text in the script itself
   - Include usage examples

4. **Follow conventions:**
   - Use consistent naming
   - Add error handling
   - Provide clear output messages
   - Exit with appropriate codes (0 = success, 1+ = error)

## Examples

### Quick deployment from scratch (Fully Automated)

```bash
tar -xzf poundcake-final-production.tar.gz
cd poundcake-timer-api
docker compose up -d

# That's it! Everything is automated:
# - Database migrations run automatically
# - StackStorm API key generated automatically
# - All services start in correct order
```

### Manual verification

```bash
# Check all services running
docker compose ps

# Check API health
curl http://localhost:8000/api/v1/health

# Check database tables
docker compose exec mariadb mysql -u poundcake -ppoundcake -e "SHOW TABLES;" poundcake

# Verify API key was generated
cat config/st2_api_key
```

### Database operations

```bash
# Check current migration version
docker compose exec api alembic current

# View migration history
docker compose exec api alembic history

# Manually run migrations (usually not needed)
docker compose exec api alembic upgrade head

# Create a new migration after model changes
docker compose exec api alembic revision --autogenerate -m "add new field"

# Copy migration from container to host
docker compose cp api:/app/alembic/versions/. ./alembic/versions/
```

## Related Documentation

- **Production Guide:** `../FINAL_PRODUCTION_GUIDE.md`
- **Migration Strategy:** `../MIGRATION_BELT_AND_SUSPENDERS.md`
- **Automated Setup:** `../AUTOMATED_STACKSTORM_SETUP.md`
- **Troubleshooting:** `../ALEMBIC_REVISION_ERROR_FIX.md`

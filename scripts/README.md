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
5. Automatically generates and configures StackStorm API key
6. Verifies deployment

This is the easiest way to get PoundCake up and running.

### setup-apikey.sh
**Purpose:** Generate and configure StackStorm API key  
**Usage:**
```bash
./scripts/setup-apikey.sh
```

**What it does:**
1. Waits for StackStorm services to be responsive
2. Authenticates with StackStorm using default credentials
3. Generates a new API key
4. Updates .env file with the new key
5. Restarts PoundCake services to apply the key

Use this when:
- Running initial setup after `docker compose up -d`
- Regenerating API keys
- Troubleshooting authentication issues

## Script Conventions

### Naming
- Bash scripts: `.sh` extension
- Python scripts: `.py` extension
- Use lowercase with hyphens for bash scripts: `setup-apikey.sh`
- Use lowercase with underscores for Python scripts: `migrate.py`

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

### Quick deployment from scratch:
```bash
tar -xzf poundcake-timer-api.tar.gz
cd poundcake-timer-api
./scripts/quickstart.sh
```

### Manual deployment:
```bash
# Start services
docker compose up -d

# Wait for initialization
sleep 60

# Setup API key
./scripts/setup-apikey.sh

# Run migrations
python api/migrate.py upgrade head
```

### Database operations:
```bash
# Check current migration version
python api/migrate.py current

# Create a new migration
python api/migrate.py create "add user preferences table"

# Apply all pending migrations
python api/migrate.py upgrade head
```

## Related Documentation

- **Deployment Guide:** `../DEPLOY.md`
- **Database Migrations:** `../docs/DATABASE_MIGRATIONS.md`
- **API Documentation:** `../docs/API_ENDPOINTS.md`
- **Troubleshooting:** `../docs/TROUBLESHOOTING.md`

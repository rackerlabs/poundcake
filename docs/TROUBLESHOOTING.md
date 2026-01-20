# Troubleshooting Common Issues

## ModuleNotFoundError: No module named 'pymysql'

### Cause
The Docker image was built before pymysql was added to dependencies, or the image wasn't rebuilt after the PostgreSQL to MariaDB migration.

### Solution

```bash
# Stop all services
docker-compose down

# Remove old images
docker-compose down --rmi all

# Rebuild with no cache
docker-compose build --no-cache

# Start services
docker-compose up -d

# Check logs
docker-compose logs worker
```

### Quick Fix

```bash
# One command to rebuild everything
docker-compose down --rmi all && docker-compose up -d --build
```

## Error: No such command 'flower'

### Cause
Flower package is not installed in the Docker image.

### Solution

This has been fixed in the latest version. Flower is now included in pyproject.toml dependencies. Rebuild the Docker image:

```bash
# Rebuild images
docker-compose build --no-cache

# Restart services
docker-compose up -d

# Verify flower is working
curl http://localhost:5555
```

### Verify Flower Installation

```bash
# Check if flower is installed in container
docker-compose exec worker pip list | grep flower

# Should show:
# flower    2.0.1
```

## Database Connection Issues

### Error: Can't connect to MySQL server

```bash
# Check MariaDB is running
docker-compose ps mariadb

# Should show: Up (healthy)

# View MariaDB logs
docker-compose logs mariadb

# Restart MariaDB
docker-compose restart mariadb

# Wait for health check
sleep 10
```

### Check Connection String

```bash
# Verify environment variables
docker-compose exec api env | grep DATABASE_URL

# Should show:
# DATABASE_URL=mysql+pymysql://poundcake:poundcake@mariadb:3306/poundcake
```

## Worker Issues

### Workers not starting

```bash
# Check worker status
docker-compose ps worker

# View worker logs
docker-compose logs worker

# Restart workers
docker-compose restart worker
```

### Workers can't connect to database

```bash
# Check if MariaDB is healthy
docker-compose ps mariadb

# Ensure workers start after MariaDB
# (This is configured in docker-compose.yml depends_on)

# Restart all services in order
docker-compose down
docker-compose up -d
```

## API Not Responding

### Check if API container is running

```bash
# View container status
docker-compose ps api

# View API logs
docker-compose logs api

# Check for errors
docker-compose logs api | grep -i error
```

### Port already in use

```bash
# Find what's using port 8000
sudo lsof -i :8000

# Kill the process or change port in docker-compose.yml
# Change "8000:8000" to "8001:8000"
```

## Redis Issues

### Redis connection refused

```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connection
docker-compose exec redis redis-cli ping
# Should return: PONG

# Check Redis logs
docker-compose logs redis
```

### Clear Redis data

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# In Redis CLI:
FLUSHALL

# Or restart with clean volume
docker-compose down -v
docker-compose up -d
```

## Complete Fresh Start

If nothing else works, completely reset:

```bash
# Stop everything
docker-compose down

# Remove all volumes (WARNING: deletes all data)
docker-compose down -v

# Remove all images
docker-compose down --rmi all

# Remove dangling images
docker system prune -a

# Rebuild and start
docker-compose up -d --build

# Wait for services
sleep 20

# Check health
curl http://localhost:8000/api/v1/health
```

## Checking Dependencies

### List installed Python packages in container

```bash
# In API container
docker-compose exec api pip list

# In worker container
docker-compose exec worker pip list

# Check for specific package
docker-compose exec api pip show pymysql
docker-compose exec worker pip show flower
```

### Verify pyproject.toml is correct

```bash
# View dependencies
cat pyproject.toml | grep -A 20 "dependencies = \["

# Should include:
# pymysql>=1.1.0
# cryptography>=41.0.0
# flower>=2.0.1
```

## Build Cache Issues

Docker sometimes uses cached layers even when files changed:

```bash
# Force complete rebuild
docker-compose build --no-cache --pull

# This:
# - Ignores all cached layers (--no-cache)
# - Pulls latest base images (--pull)
```

## Permission Issues

### Can't write to logs or volumes

```bash
# Check volume permissions
docker-compose exec api ls -la /app

# Fix ownership (if needed)
docker-compose exec -u root api chown -R appuser:appuser /app
```

## Network Issues

### Containers can't communicate

```bash
# Check networks
docker network ls

# Inspect network
docker network inspect poundcake-api_default

# Recreate networks
docker-compose down
docker network prune
docker-compose up -d
```

## Viewing Real-Time Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f worker
docker-compose logs -f mariadb

# Last 100 lines
docker-compose logs --tail=100 worker

# Follow new logs only
docker-compose logs -f --tail=0 worker
```

## Health Check Failures

### API health check failing

```bash
# Check health endpoint manually
curl -v http://localhost:8000/api/v1/health/live

# Check container health
docker inspect poundcake-api-api-1 | grep -A 10 Health
```

### Database health check failing

```bash
# Check MariaDB health script
docker-compose exec mariadb healthcheck.sh --connect --innodb_initialized

# Manual connection test
docker-compose exec mariadb mariadb -upoundcake -ppoundcake -e "SELECT 1"
```

## Upgrading / Updating

### After pulling new code

```bash
# Always rebuild after code changes
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### After changing pyproject.toml

```bash
# Must rebuild to install new dependencies
docker-compose build --no-cache
docker-compose up -d
```

### After changing docker-compose.yml

```bash
# Just restart (no rebuild needed for config changes)
docker-compose down
docker-compose up -d
```

## Common Mistakes

### 1. Not rebuilding after dependency changes
**Problem:** New dependencies not available
**Solution:** Always run `docker-compose build` after changing pyproject.toml

### 2. Using cached layers
**Problem:** Changes not reflected in container
**Solution:** Use `--no-cache` flag when building

### 3. Ports already in use
**Problem:** Can't start services
**Solution:** Check with `lsof` and change ports or kill conflicting processes

### 4. Old volumes with incompatible data
**Problem:** Database errors on startup
**Solution:** Remove volumes with `docker-compose down -v` (WARNING: deletes data)

### 5. Not waiting for services to be ready
**Problem:** Services fail to connect
**Solution:** Use health checks and wait longer (15-30 seconds)

## Getting Help

### Collect diagnostic information

```bash
# Create diagnostic report
echo "=== Docker Version ===" > diagnostic.txt
docker --version >> diagnostic.txt
echo "" >> diagnostic.txt

echo "=== Docker Compose Version ===" >> diagnostic.txt
docker-compose --version >> diagnostic.txt
echo "" >> diagnostic.txt

echo "=== Container Status ===" >> diagnostic.txt
docker-compose ps >> diagnostic.txt
echo "" >> diagnostic.txt

echo "=== API Logs ===" >> diagnostic.txt
docker-compose logs --tail=50 api >> diagnostic.txt
echo "" >> diagnostic.txt

echo "=== Worker Logs ===" >> diagnostic.txt
docker-compose logs --tail=50 worker >> diagnostic.txt
echo "" >> diagnostic.txt

echo "=== MariaDB Logs ===" >> diagnostic.txt
docker-compose logs --tail=50 mariadb >> diagnostic.txt
echo "" >> diagnostic.txt

# View report
cat diagnostic.txt
```

## Quick Reference

```bash
# Rebuild everything
docker-compose down --rmi all && docker-compose up -d --build

# Fresh start with no data
docker-compose down -v && docker-compose up -d --build

# View specific service logs
docker-compose logs -f worker

# Check service health
curl http://localhost:8000/api/v1/health

# Enter container shell
docker-compose exec api bash

# Check installed packages
docker-compose exec worker pip list

# Test database connection
docker-compose exec mariadb mariadb -upoundcake -ppoundcake -e "SHOW DATABASES;"
```

## Prevention

To avoid these issues in the future:

1. Always rebuild after changing dependencies
2. Use `--no-cache` if changes aren't reflected
3. Wait for health checks before testing
4. Check logs immediately if something fails
5. Keep Docker and Docker Compose updated

## Quick Fix Script

Save as `fix.sh`:

```bash
#!/bin/bash
echo "Fixing PoundCake API..."
docker-compose down --rmi all
docker-compose build --no-cache
docker-compose up -d
echo "Waiting for services..."
sleep 20
echo "Testing..."
curl http://localhost:8000/api/v1/health
echo ""
echo "Done!"
```

Run with:
```bash
chmod +x fix.sh
./fix.sh
```

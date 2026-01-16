#!/bin/bash
# Quick fix script - Rebuilds Docker images and restarts services

set -e

echo "PoundCake API - Quick Fix"
echo "=========================="
echo ""
echo "This will fix common issues:"
echo "  - ModuleNotFoundError: No module named 'pymysql'"
echo "  - Error: No such command 'flower'"
echo "  - SQLAlchemy 2.0 text() requirement"
echo ""
echo "Steps:"
echo "  1. Stop all services"
echo "  2. Remove old images"
echo "  3. Rebuild with no cache"
echo "  4. Start services"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Step 1: Stopping services..."
docker-compose down

echo ""
echo "Step 2: Removing old images..."
docker-compose down --rmi all

echo ""
echo "Step 3: Rebuilding images (this may take a few minutes)..."
docker-compose build --no-cache

echo ""
echo "Step 4: Starting services..."
docker-compose up -d

echo ""
echo "Step 5: Waiting for services to be ready..."
sleep 20

echo ""
echo "Step 6: Testing services..."

# Test API
if curl -s http://localhost:8000/api/v1/health/live > /dev/null 2>&1; then
    echo "  API: OK"
else
    echo "  API: FAILED (check logs: docker-compose logs api)"
fi

# Test Flower
if curl -s http://localhost:5555 > /dev/null 2>&1; then
    echo "  Flower: OK"
else
    echo "  Flower: FAILED (check logs: docker-compose logs flower)"
fi

# Check Workers
WORKER_COUNT=$(docker-compose ps worker | grep -c "Up" || echo "0")
echo "  Workers: $WORKER_COUNT running"

# Check MariaDB
if docker-compose exec -T mariadb mariadb -upoundcake -ppoundcake -e "SELECT 1" > /dev/null 2>&1; then
    echo "  MariaDB: OK"
else
    echo "  MariaDB: FAILED (check logs: docker-compose logs mariadb)"
fi

# Check database health
echo ""
echo "Testing database health check..."
HEALTH=$(curl -s http://localhost:8000/api/v1/health)
if echo "$HEALTH" | grep -q '"database":"healthy"'; then
    echo "  Database health: OK"
else
    echo "  Database health: ISSUE"
    echo "  Response: $HEALTH"
fi

echo ""
echo "Done!"
echo ""
echo "Services:"
echo "  API:    http://localhost:8000"
echo "  Docs:   http://localhost:8000/docs"
echo "  Flower: http://localhost:5555"
echo ""
echo "View logs: docker-compose logs -f"
echo ""

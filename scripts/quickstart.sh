#!/bin/bash
# PoundCake Quick Start Script
# Automates the complete deployment process

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================"
echo "PoundCake Quick Start"
echo "========================================"
echo ""
echo "This script will:"
echo "  1. Check prerequisites"
echo "  2. Create .env configuration"
echo "  3. Start all services"
echo "  4. Wait for initialization"
echo "  5. Setup StackStorm API key"
echo "  6. Verify deployment"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Step 1: Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed"
    exit 1
fi
echo "✓ Docker found"

# Check Docker Compose
if ! command -v docker compose &> /dev/null; then
    echo "ERROR: Docker Compose is not installed"
    exit 1
fi
echo "✓ Docker Compose found"

# Check Docker daemon
if ! docker ps &> /dev/null; then
    echo "ERROR: Docker daemon is not running"
    exit 1
fi
echo "✓ Docker daemon running"

echo ""
echo "Step 2: Creating configuration..."

if [ -f ".env" ]; then
    echo "⚠ .env file already exists"
    read -p "Overwrite with defaults? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp .env.example .env
        echo "✓ .env file created from template"
    else
        echo "✓ Using existing .env file"
    fi
else
    cp .env.example .env
    echo "✓ .env file created from template"
fi

echo ""
echo "Step 3: Starting services..."
echo "This will start 12+ services (may take a moment)..."

docker compose up -d

echo "✓ Services started"

echo ""
echo "Step 4: Waiting for initialization..."
echo "Services need 60-90 seconds to fully initialize..."
echo ""

WAIT_TIME=60
for i in $(seq $WAIT_TIME -1 1); do
    printf "\rWaiting... %2ds remaining" $i
    sleep 1
done
printf "\r✓ Wait complete                   \n"

echo ""
echo "Step 5: Setting up StackStorm API key..."

if [ -x "$SCRIPT_DIR/setup-apikey.sh" ]; then
    "$SCRIPT_DIR/setup-apikey.sh"
else
    echo "ERROR: setup-apikey.sh not found or not executable"
    exit 1
fi

echo ""
echo "Step 6: Verifying deployment..."

# Check services
echo ""
echo "Service Status:"
docker compose ps

# Test API health
echo ""
echo "Testing API health..."
if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo "✓ PoundCake API is healthy"
    curl -s http://localhost:8000/api/v1/health | python3 -m json.tool 2>/dev/null || true
else
    echo "⚠ PoundCake API is not responding yet"
    echo "  (May need more time to fully initialize)"
fi

echo ""
echo "========================================"
echo "✓ Quick Start Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Create your first recipe:"
echo "     curl -X POST http://localhost:8000/api/recipes/ \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d @examples/recipe-hostdown.json"
echo ""
echo "  2. View API documentation:"
echo "     http://localhost:8000/docs"
echo ""
echo "  3. Monitor logs:"
echo "     docker compose logs -f"
echo ""
echo "  4. Check service status:"
echo "     docker compose ps"
echo ""
echo "Available endpoints:"
echo "  - PoundCake API: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - RabbitMQ Management: http://localhost:15672"
echo ""
echo "To stop services:"
echo "  docker compose down"
echo ""
echo "To stop and remove all data:"
echo "  docker compose down -v"
echo ""

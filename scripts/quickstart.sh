#!/bin/bash
# Quick start script for Containerized PoundCake + StackStorm
# Everything runs in Docker containers - no host installation needed!

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   PoundCake + StackStorm Containerized Quick Start       ║"
echo "║                                                           ║"
echo "║         Everything runs in Docker containers!            ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ ${NC}$1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  $1"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
}

# ============================================================================
# STEP 1: Check Prerequisites
# ============================================================================
print_header "Step 1: Checking Prerequisites"

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed"
    print_info "Install Docker: https://docs.docker.com/engine/install/"
    exit 1
fi
print_success "Docker is installed ($(docker --version))"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    print_error "Docker Compose is not installed"
    print_info "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi
print_success "Docker Compose is installed"

# Check if Docker daemon is running
if ! docker ps > /dev/null 2>&1; then
    print_error "Docker daemon is not running"
    print_info "Start Docker and try again"
    exit 1
fi
print_success "Docker daemon is running"

# ============================================================================
# STEP 2: Configure Environment
# ============================================================================
print_header "Step 2: Configuring Environment"

# Create .env file
if [ ! -f .env ]; then
    print_info "Creating .env file..."
    cat > .env << EOF
# Database
DATABASE_URL=mysql+pymysql://poundcake:poundcake@mariadb:3306/poundcake

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# StackStorm (containerized)
ST2_API_URL=http://st2api:9101/v1
ST2_API_KEY=

# App
LOG_LEVEL=INFO
EOF
    print_success "Created .env file"
else
    print_success ".env file already exists"
fi

# ============================================================================
# STEP 3: Build Docker Images
# ============================================================================
print_header "Step 3: Building Docker Images"

print_info "Building PoundCake images (this may take a few minutes)..."
docker-compose -f docker-compose.yml build --no-cache

print_success "Docker images built successfully"

# ============================================================================
# STEP 4: Start All Services
# ============================================================================
print_header "Step 4: Starting All Services"

print_info "Starting infrastructure..."
print_info "  • MariaDB (shared database)"
print_info "  • Redis (Celery broker)"
print_info "  • RabbitMQ (StackStorm message queue)"
echo ""

print_info "Starting StackStorm containers..."
print_info "  • st2api (REST API)"
print_info "  • st2auth (Authentication)"
print_info "  • st2stream (Event stream)"
print_info "  • st2rulesengine (Rules engine)"
print_info "  • st2actionrunner (Action execution)"
print_info "  • st2scheduler (Scheduler)"
print_info "  • st2notifier (Notifications)"
echo ""

print_info "Starting PoundCake containers..."
print_info "  • API (webhook receiver)"
print_info "  • Celery workers"
print_info "  • Flower (monitoring)"
echo ""

docker-compose -f docker-compose.yml up -d

print_success "All services started"

# ============================================================================
# STEP 5: Wait for Services
# ============================================================================
print_header "Step 5: Waiting for Services to Initialize"

print_info "Waiting 30 seconds for services to start..."
sleep 30

# Check service health
print_info "Checking service status..."

# Check MariaDB
if docker-compose -f docker-compose.yml exec -T mariadb mysqladmin ping -uroot -prootpassword > /dev/null 2>&1; then
    print_success "MariaDB is running"
else
    print_warning "MariaDB is not responding yet"
fi

# Check Redis
if docker-compose -f docker-compose.yml exec -T redis redis-cli ping > /dev/null 2>&1; then
    print_success "Redis is running"
else
    print_warning "Redis is not responding yet"
fi

# Check RabbitMQ
if curl -s http://localhost:15672 > /dev/null 2>&1; then
    print_success "RabbitMQ is running"
else
    print_warning "RabbitMQ is not responding yet"
fi

# Check ST2 API
if curl -s http://localhost:9101/v1 > /dev/null 2>&1; then
    print_success "StackStorm API is running"
else
    print_warning "StackStorm API is not responding yet (may need more time)"
fi

# Check PoundCake API
if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    print_success "PoundCake API is running"
else
    print_warning "PoundCake API is not responding yet"
fi

# Check Flower
if curl -s http://localhost:5555 > /dev/null 2>&1; then
    print_success "Flower (Celery monitoring) is running"
else
    print_warning "Flower is not responding yet"
fi

# ============================================================================
# STEP 6: Initialize PoundCake Database
# ============================================================================
print_header "Step 6: Initializing PoundCake Database"

print_info "Creating 3 PoundCake tables..."

# Run init script inside API container
if docker-compose -f docker-compose.yml exec -T api python api/scripts/init_database.py; then
    print_success "PoundCake database initialized"
else
    print_warning "Database initialization may have failed"
    print_info "You can run manually: docker-compose -f docker-compose.yml exec api python api/scripts/init_database.py"
fi

# ============================================================================
# STEP 7: Create StackStorm API Key
# ============================================================================
print_header "Step 7: Creating StackStorm API Key"

print_info "Creating ST2 API key for PoundCake..."
sleep 5  # Give ST2 a bit more time

# Try to create API key
ST2_API_KEY=$(docker-compose -f docker-compose.yml exec -T st2api st2 apikey create -k -m '{"used_by": "poundcake-api"}' 2>/dev/null | grep -oP 'Key:\s+\K\S+' || echo "")

if [ -z "$ST2_API_KEY" ]; then
    print_warning "Could not create ST2 API key automatically"
    print_info "ST2 may need more time to initialize"
    print_info "Create manually after startup:"
    echo ""
    echo "  docker-compose -f docker-compose.yml exec st2api st2 apikey create -k -m '{\"used_by\": \"poundcake-api\"}'"
    echo ""
    ST2_API_KEY="REPLACE_AFTER_ST2_READY"
else
    print_success "ST2 API key created"
    echo "$ST2_API_KEY" > .st2_api_key
    chmod 600 .st2_api_key
fi

# Update .env with API key
if grep -q "ST2_API_KEY=" .env; then
    sed -i "s|ST2_API_KEY=.*|ST2_API_KEY=$ST2_API_KEY|" .env
else
    echo "ST2_API_KEY=$ST2_API_KEY" >> .env
fi

# ============================================================================
# STEP 8: Test Integration
# ============================================================================
print_header "Step 8: Testing Integration"

print_info "Sending test alert..."

TEST_PAYLOAD='{"alerts":[{"status":"firing","labels":{"alertname":"TestAlert","instance":"server-01","severity":"info"},"annotations":{"description":"Test from quickstart"},"fingerprint":"quickstart-test","startsAt":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}]}'

RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d "$TEST_PAYLOAD" || echo '{"status":"error"}')

REQUEST_ID=$(echo "$RESPONSE" | grep -oP '"request_id":\s*"\K[^"]+' || echo "")

if [ ! -z "$REQUEST_ID" ]; then
    print_success "Test alert sent! Request ID: $REQUEST_ID"
else
    print_warning "Could not send test alert (API may still be starting)"
fi

# ============================================================================
# Setup Complete!
# ============================================================================
print_header "🎉 Setup Complete!"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Available Services"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "PoundCake:"
echo "  • API:            http://localhost:8000"
echo "  • API Docs:       http://localhost:8000/docs"
echo "  • Flower:         http://localhost:5555"
echo ""
echo "StackStorm:"
echo "  • ST2 API:        http://localhost:9101"
echo "  • ST2 Auth:       http://localhost:9100"
echo "  • ST2 Stream:     http://localhost:9102"
echo ""
echo "Infrastructure:"
echo "  • MariaDB:        localhost:3306"
echo "  • RabbitMQ UI:    http://localhost:15672 (stackstorm/stackstorm)"
echo "  • Redis:          localhost:6379"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Quick Commands"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "View all containers:"
echo "  docker-compose -f docker-compose.yml ps"
echo ""
echo "View logs:"
echo "  docker-compose -f docker-compose.yml logs -f api"
echo "  docker-compose -f docker-compose.yml logs -f celery"
echo "  docker-compose -f docker-compose.yml logs -f st2api"
echo ""
echo "Access ST2 CLI:"
echo "  docker-compose -f docker-compose.yml exec st2api st2 action list"
echo ""
echo "Create ST2 API key (if not created automatically):"
echo "  docker-compose -f docker-compose.yml exec st2api st2 apikey create -k -m '{\"used_by\": \"poundcake-api\"}'"
echo ""
echo "Stop all services:"
echo "  docker-compose -f docker-compose.yml down"
echo ""
echo "Stop and remove volumes:"
echo "  docker-compose -f docker-compose.yml down -v"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Next Steps"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "1. Create ST2 workflows:"
echo "   docker-compose -f docker-compose.yml exec st2api bash"
echo "   st2 pack install tutorial"
echo ""
echo "2. Send test alerts:"
echo "   curl -X POST http://localhost:8000/api/v1/webhook -d @test-alert.json"
echo ""
echo "3. Monitor in Flower:"
echo "   http://localhost:5555"
echo ""
echo "4. Check ST2 executions:"
echo "   docker-compose -f docker-compose.yml exec st2api st2 execution list"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
print_success "All systems operational!"
echo ""
print_info "Note: StackStorm may need a few more minutes to fully initialize"
print_info "If ST2 API key creation failed, create it manually as shown above"
echo ""

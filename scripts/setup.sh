#!/bin/bash
# PoundCake Complete Setup Script
# Combines Docker container setup, health checks, and CLI installation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║   PoundCake + StackStorm - Complete Setup                ║"
echo "║                                                           ║"
echo "║         Everything runs in Docker containers!            ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Helper functions
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

# Check Python 3
if ! command -v python3 &> /dev/null; then
    print_warning "Python 3 not found - CLI installation will be skipped"
    SKIP_CLI=true
else
    print_success "Python 3 is installed"
    SKIP_CLI=false
fi

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    print_error "docker-compose.yml not found. Please run this script from the repository root."
    exit 1
fi

# ============================================================================
# STEP 2: Build and Start Containers
# ============================================================================
print_header "Step 2: Building and Starting Containers"

print_info "Building Docker images (this may take a few minutes)..."
docker-compose build --no-cache

print_info "Starting all services..."
print_info "  Infrastructure: MariaDB, Redis, RabbitMQ"
print_info "  StackStorm: 7 containers (api, auth, stream, rules, actions, scheduler, notifier)"
print_info "  PoundCake: API, Celery workers, Flower, Web UI"
echo ""

docker-compose up -d

if [ $? -eq 0 ]; then
    print_success "All containers started successfully"
else
    print_error "Failed to start containers"
    exit 1
fi

# ============================================================================
# STEP 3: Wait for Services to Initialize
# ============================================================================
print_header "Step 3: Waiting for Services to Initialize"

print_info "Waiting for services to start (30 seconds)..."
sleep 30

# Check service health
print_info "Checking service status..."

# Check MariaDB
if docker-compose exec -T mariadb mysqladmin ping -uroot -prootpassword > /dev/null 2>&1; then
    print_success "MariaDB is running"
else
    print_warning "MariaDB is not responding yet"
fi

# Check Redis
if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
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

# Check StackStorm API
if curl -s http://localhost:9101/v1 > /dev/null 2>&1; then
    print_success "StackStorm API is running"
else
    print_warning "StackStorm API is not responding yet (may need more time)"
fi

# Check PoundCake API with retries
print_info "Waiting for PoundCake API..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        print_success "PoundCake API is running"
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    print_error "API did not become ready in time"
    print_info "Showing API logs..."
    docker-compose logs --tail=50 api
    exit 1
fi

# Check Flower
if curl -s http://localhost:5555 > /dev/null 2>&1; then
    print_success "Flower (Celery monitoring) is running"
else
    print_warning "Flower is not responding yet"
fi

# Check Web UI
if curl -s http://localhost:8080 > /dev/null 2>&1; then
    print_success "Web UI is running"
else
    print_warning "Web UI is not responding yet"
fi

# ============================================================================
# STEP 4: Create StackStorm API Key
# ============================================================================
print_header "Step 4: Creating StackStorm API Key"

print_info "Creating ST2 API key for PoundCake..."
sleep 5  # Give ST2 a bit more time

# Try to create API key
ST2_API_KEY=$(docker-compose exec -T st2api st2 apikey create -k -m '{"used_by": "poundcake-api"}' 2>/dev/null | grep -oP 'Key:\s+\K\S+' || echo "")

if [ -z "$ST2_API_KEY" ]; then
    print_warning "Could not create ST2 API key automatically"
    print_info "StackStorm may need more time to initialize"
    print_info "Create manually after startup with:"
    echo ""
    echo "  docker-compose exec st2api st2 apikey create -k -m '{\"used_by\": \"poundcake-api\"}'"
    echo ""
else
    print_success "ST2 API key created: $ST2_API_KEY"
    echo "$ST2_API_KEY" > .st2_api_key
    chmod 600 .st2_api_key
    print_info "API key saved to .st2_api_key"
fi

# ============================================================================
# STEP 5: Install CLI Tool
# ============================================================================
print_header "Step 5: Installing CLI Tool"

if [ "$SKIP_CLI" = true ]; then
    print_warning "Skipping CLI installation (Python 3 not found)"
else
    print_info "Installing PoundCake CLI (pcake)..."
    
    if python3 -m pip install -e . > /dev/null 2>&1; then
        print_success "CLI tool installed successfully"
        
        # Configure environment
        if ! grep -q "POUNDCAKE_URL" ~/.bashrc 2>/dev/null; then
            echo "" >> ~/.bashrc
            echo "# PoundCake CLI Configuration" >> ~/.bashrc
            echo "export POUNDCAKE_URL=http://localhost:8000" >> ~/.bashrc
            print_success "Added POUNDCAKE_URL to ~/.bashrc"
        fi
        
        # Export for current session
        export POUNDCAKE_URL=http://localhost:8000
    else
        print_warning "Failed to install CLI tool"
    fi
fi

# ============================================================================
# STEP 6: Test Integration
# ============================================================================
print_header "Step 6: Testing Integration"

print_info "Sending test webhook..."

TEST_PAYLOAD='{"alerts":[{"status":"firing","labels":{"alertname":"TestAlert","instance":"server-01","severity":"info"},"annotations":{"description":"Test from setup"},"fingerprint":"setup-test-'$(date +%s)'","startsAt":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}]}'

RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d "$TEST_PAYLOAD" || echo '{"status":"error"}')

REQUEST_ID=$(echo "$RESPONSE" | grep -oP '"request_id":\s*"\K[^"]+' || echo "")

if [ ! -z "$REQUEST_ID" ]; then
    print_success "Test alert sent! Request ID: $REQUEST_ID"
    print_info "View in Flower: http://localhost:5555"
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
echo "  • Web UI:         http://localhost:8080"
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
echo "  • MariaDB:        localhost:3306 (poundcake/poundcake)"
echo "  • RabbitMQ UI:    http://localhost:15672 (stackstorm/stackstorm)"
echo "  • Redis:          localhost:6379"
echo ""

if [ "$SKIP_CLI" = false ]; then
    echo "═══════════════════════════════════════════════════════════"
    echo "  CLI Quick Start"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo "Test CLI:        pcake --help"
    echo "List alerts:     pcake alerts list"
    echo "Watch alerts:    pcake alerts watch"
    echo ""
    echo "Note: Run 'source ~/.bashrc' or start a new terminal"
    echo ""
fi

echo "═══════════════════════════════════════════════════════════"
echo "  Quick Commands"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "View containers:"
echo "  docker-compose ps"
echo ""
echo "View logs:"
echo "  docker-compose logs -f api"
echo "  docker-compose logs -f celery"
echo "  docker-compose logs -f st2api"
echo ""
echo "Send test alert:"
echo "  curl -X POST http://localhost:8000/api/v1/webhook \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"alerts\":[{\"labels\":{\"alertname\":\"Test\"}}]}'"
echo ""
echo "Access ST2 CLI:"
echo "  docker-compose exec st2api st2 action list"
echo ""
echo "Stop services:"
echo "  docker-compose down"
echo ""
echo "Stop and remove volumes:"
echo "  docker-compose down -v"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  Next Steps"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "1. Explore the Web UI:"
echo "   http://localhost:8080"
echo ""
echo "2. View API documentation:"
echo "   http://localhost:8000/docs"
echo ""
echo "3. Monitor Celery tasks:"
echo "   http://localhost:5555"
echo ""
echo "4. Create ST2 workflows:"
echo "   docker-compose exec st2api bash"
echo "   st2 pack install tutorial"
echo ""
echo "5. Query by request_id:"
echo "   curl http://localhost:8000/api/requests/$REQUEST_ID/status"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo ""

# Display container status
print_info "Container Status:"
echo ""
docker-compose ps

echo ""
print_success "All systems operational!"
echo ""

if [ ! -z "$ST2_API_KEY" ]; then
    print_info "ST2 API Key saved to .st2_api_key"
else
    print_warning "Remember to create ST2 API key manually if needed"
fi

echo ""

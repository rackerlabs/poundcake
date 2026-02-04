#!/bin/bash
# StackStorm Registration Troubleshooting Script
# Run this to diagnose content registration issues

set -e

echo "========================================="
echo "  StackStorm Registration Diagnostics"
echo "========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 1. Check if services are running
echo "1. Checking service status..."

if docker compose ps stackstorm-bootstrap 2>/dev/null | grep -q "Exited (0)"; then
    success "stackstorm-bootstrap completed successfully"
elif docker compose ps stackstorm-bootstrap 2>/dev/null | grep -q "Up"; then
    warning "stackstorm-bootstrap is still running (should be Exited (0))"
elif docker compose ps stackstorm-bootstrap 2>/dev/null | grep -q "Exited"; then
    error "stackstorm-bootstrap exited with non-zero status"
else
    warning "stackstorm-bootstrap service not found"
fi

if docker compose ps st2client 2>/dev/null | grep -q "Up"; then
    success "st2client is running"
else
    warning "st2client is not running"
fi

if docker compose ps stackstorm-actionrunner | grep -q "Up"; then
    success "stackstorm-actionrunner is running"
else
    error "stackstorm-actionrunner is not running"
fi

if docker compose ps stackstorm-api | grep -q "healthy"; then
    success "stackstorm-api is healthy"
else
    error "stackstorm-api is not healthy"
fi

echo ""

# 2. Check registration logs
echo "2. Checking registration logs..."
echo ""
echo "=== Bootstrap Service Registration Logs ==="
docker compose logs stackstorm-bootstrap 2>/dev/null | grep -i "register" | tail -5 || \
docker compose logs st2client 2>/dev/null | grep -i "register" | tail -5 || \
warning "Could not find registration logs in bootstrap service"

echo ""
echo "=== ActionRunner Registration Logs ==="
docker compose logs stackstorm-actionrunner | grep -i "register" | tail -5 || \
warning "Could not find registration logs in actionrunner"

echo ""

# 3. Check packs directory
echo "3. Checking packs directory in actionrunner..."
PACK_COUNT=$(docker compose exec -T stackstorm-actionrunner sh -c "ls -1 /opt/stackstorm/packs 2>/dev/null | wc -l" || echo "0")

if [ "$PACK_COUNT" -gt 0 ]; then
    success "Found $PACK_COUNT packs in /opt/stackstorm/packs"
    echo ""
    echo "Installed packs:"
    docker compose exec -T stackstorm-actionrunner ls -la /opt/stackstorm/packs/ | head -15
else
    error "No packs found in /opt/stackstorm/packs"
fi

echo ""

# 4. Check core pack specifically
echo "4. Checking core pack..."
if docker compose exec -T stackstorm-actionrunner test -d /opt/stackstorm/packs/core; then
    success "Core pack directory exists"
    
    # Check if actions exist
    CORE_ACTIONS=$(docker compose exec -T stackstorm-actionrunner sh -c "ls -1 /opt/stackstorm/packs/core/actions/ 2>/dev/null | wc -l" || echo "0")
    if [ "$CORE_ACTIONS" -gt 0 ]; then
        success "Core pack has $CORE_ACTIONS actions"
    else
        error "Core pack exists but has no actions"
    fi
else
    error "Core pack directory does not exist"
fi

echo ""

# 5. Try to list packs using st2 CLI
echo "5. Testing ST2 CLI functionality..."
if docker compose exec -T stackstorm-actionrunner st2 pack list >/dev/null 2>&1; then
    success "ST2 CLI can list packs"
    echo ""
    echo "Registered packs:"
    docker compose exec -T stackstorm-actionrunner st2 pack list | head -15
else
    error "ST2 CLI cannot list packs"
    echo "This might indicate authentication or API connectivity issues"
fi

echo ""

# 6. Try to list core actions
echo "6. Testing core pack actions..."
if docker compose exec -T stackstorm-actionrunner st2 action list --pack=core >/dev/null 2>&1; then
    success "Core pack actions are registered and accessible"
    echo ""
    echo "Sample core actions:"
    docker compose exec -T stackstorm-actionrunner st2 action list --pack=core | head -10
else
    error "Core pack actions are not accessible"
fi

echo ""

# 7. Try the actual command that was failing
echo "7. Testing st2_run_local command..."
if docker compose exec -T stackstorm-actionrunner /opt/stackstorm/st2/bin/python3 -m st2common.bin.st2_run_local core.local cmd="echo 'Test'" >/dev/null 2>&1; then
    success "st2_run_local command works!"
    echo ""
    echo "Test output:"
    docker compose exec -T stackstorm-actionrunner /opt/stackstorm/st2/bin/python3 -m st2common.bin.st2_run_local core.local cmd="echo 'Brain is alive'"
else
    error "st2_run_local command still fails"
    echo ""
    echo "Error output:"
    docker compose exec -T stackstorm-actionrunner /opt/stackstorm/st2/bin/python3 -m st2common.bin.st2_run_local core.local cmd="echo 'Test'" 2>&1 | head -10
fi

echo ""
echo "========================================="
echo "  Diagnostics Complete"
echo "========================================="
echo ""

# Summary and recommendations
echo "Summary and Recommendations:"
echo ""

if [ "$PACK_COUNT" -eq 0 ]; then
    echo "❌ CRITICAL: No packs registered at all"
    echo "   → Run: docker compose restart stackstorm-actionrunner"
    echo "   → Check logs: docker compose logs stackstorm-actionrunner"
    echo ""
fi

if ! docker compose exec -T stackstorm-actionrunner test -d /opt/stackstorm/packs/core; then
    echo "❌ CRITICAL: Core pack missing"
    echo "   → Run manual registration:"
    echo "   docker compose exec stackstorm-actionrunner st2-register-content --register-all --register-setup-virtualenvs --config-file /etc/st2/st2.conf"
    echo ""
fi

if docker compose exec -T stackstorm-actionrunner st2 action list --pack=core >/dev/null 2>&1; then
    echo "✅ Core pack is working correctly"
    echo "   You should be able to run StackStorm actions now"
else
    echo "❌ Core pack registered but not functional"
    echo "   → Check StackStorm API connectivity"
    echo "   → Verify authentication is working"
    echo "   → Check: docker compose exec stackstorm-actionrunner st2 action list"
fi

echo ""

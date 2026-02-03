#!/bin/bash
# Generate StackStorm API Key and Update .env
# This script uses st2 CLI for proper StackStorm interaction

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================"
echo "StackStorm API Key Generator"
echo "========================================"
echo ""

echo "Waiting for services to start..."
echo "This may take 30-60 seconds..."
echo ""

echo "Checking StackStorm services..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    # Check if st2 CLI is available and working
    if docker compose exec -T stackstorm-api /opt/stackstorm/st2/bin/st2 --version >/dev/null 2>&1; then
        echo "[OK] StackStorm services are responding"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo "  Waiting... ($WAITED/${MAX_WAIT}s)"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo "ERROR: StackStorm services did not become available"
    echo ""
    echo "Troubleshooting:"
    echo "  docker compose ps"
    echo "  docker compose logs stackstorm-api"
    echo "  docker compose logs stackstorm-auth"
    exit 1
fi

echo ""
echo "Step 1: Authenticating with StackStorm..."

# Get authentication token using st2 CLI
TOKEN=$(docker compose exec -T stackstorm-api /opt/stackstorm/st2/bin/st2 auth st2admin -p Ch@ngeMe -t 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo ""
    echo "ERROR: Failed to authenticate"
    echo ""
    echo "Troubleshooting:"
    echo "  docker compose logs stackstorm-auth"
    echo "  docker compose exec stackstorm-api /opt/stackstorm/st2/bin/st2 auth st2admin -p Ch@ngeMe"
    exit 1
fi

echo "[OK] Authentication successful"
echo ""

echo "Step 2: Creating API key..."

# Create API key using st2 CLI
API_KEY=$(docker compose exec -T stackstorm-api /opt/stackstorm/st2/bin/st2 apikey create -k -t "$TOKEN" 2>/dev/null)

if [ -z "$API_KEY" ]; then
    echo ""
    echo "ERROR: Failed to create API key"
    echo ""
    echo "Troubleshooting:"
    echo "  docker compose logs stackstorm-api"
    echo "  docker compose exec stackstorm-api /opt/stackstorm/st2/bin/st2 apikey list -t \"$TOKEN\""
    exit 1
fi

echo "[OK] API key created successfully"
echo "    Key: $API_KEY"
echo ""

echo "Step 3: Updating .env file..."
# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

# Create backup
cp .env .env.backup

# Update or add ST2_API_KEY in .env
if grep -q "^ST2_API_KEY=" .env 2>/dev/null; then
    # Update existing line
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^ST2_API_KEY=.*|ST2_API_KEY=$API_KEY|" .env
    else
        sed -i "s|^ST2_API_KEY=.*|ST2_API_KEY=$API_KEY|" .env
    fi
    echo "[OK] Updated existing ST2_API_KEY in .env"
elif grep -q "^#ST2_API_KEY=" .env 2>/dev/null; then
    # Uncomment and update
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^#ST2_API_KEY=.*|ST2_API_KEY=$API_KEY|" .env
    else
        sed -i "s|^#ST2_API_KEY=.*|ST2_API_KEY=$API_KEY|" .env
    fi
    echo "[OK] Uncommented and set ST2_API_KEY in .env"
else
    # Add new line
    echo "" >> .env
    echo "# StackStorm API Key (auto-generated)" >> .env
    echo "ST2_API_KEY=$API_KEY" >> .env
    echo "[OK] Added ST2_API_KEY to .env"
fi

# Verify the change
if grep -q "^ST2_API_KEY=$API_KEY" .env; then
    echo "[OK] Verified .env contains correct API key"
else
    echo "[WARN] Could not verify .env update. Please check manually."
    echo "      Expected line: ST2_API_KEY=$API_KEY"
fi

echo ""
echo "Step 4: Restarting PoundCake services..."
docker compose restart api oven timer

# Wait a moment for services to restart
sleep 5

echo ""
echo "========================================"
echo "[OK] Configuration Complete!"
echo "========================================"
echo ""
echo "Your StackStorm API key has been generated and configured."
echo ""
echo "API Key: $API_KEY"
echo ""
echo "Services restarted:"
echo "  - poundcake-api"
echo "  - poundcake-oven"
echo "  - poundcake-timer"
echo ""
echo "Verify the setup:"
echo "  docker compose ps"
echo "  curl http://localhost:8000/api/v1/health"
echo ""
echo "If health check still shows 'unhealthy', wait 10 more seconds for services to fully initialize."
echo ""

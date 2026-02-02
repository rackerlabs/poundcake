#!/bin/bash
# Generate StackStorm API Key and Update .env
# This script automates the API key generation process

set -e

echo "========================================"
echo "StackStorm API Key Generator"
echo "========================================"
echo ""

echo "Waiting for services to start..."
echo "This may take 30-60 seconds..."
echo ""

# Wait for StackStorm API to be responsive
echo "Checking StackStorm API..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if docker exec stackstorm-api curl -sf http://localhost:9101/v1 2>&1 | grep -q "401\|actions"; then
        echo "✓ StackStorm API is responding"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo "  Waiting... ($WAITED/${MAX_WAIT}s)"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo "ERROR: StackStorm API did not become available"
    echo ""
    echo "Troubleshooting:"
    echo "  docker compose ps"
    echo "  docker logs stackstorm-api"
    exit 1
fi

# Wait for StackStorm Auth to be responsive
echo ""
echo "Checking StackStorm Auth..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if docker exec stackstorm-auth curl -sf http://localhost:9100/v1 2>&1 | grep -q "auth\|tokens"; then
        echo "✓ StackStorm Auth is responding"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo "  Waiting... ($WAITED/${MAX_WAIT}s)"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo "ERROR: StackStorm Auth did not become available"
    echo ""
    echo "Troubleshooting:"
    echo "  docker compose ps"
    echo "  docker logs stackstorm-auth"
    exit 1
fi

echo ""
echo "Step 1: Authenticating with StackStorm..."
# Get authentication token
TOKEN=$(docker exec stackstorm-auth st2 auth st2admin -p Ch@ngeMe -t 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo ""
    echo "ERROR: Failed to authenticate"
    echo ""
    echo "Troubleshooting:"
    echo "  docker logs stackstorm-auth"
    echo "  docker exec stackstorm-auth st2 auth st2admin -p Ch@ngeMe"
    exit 1
fi

echo "✓ Authentication successful"
echo ""

echo "Step 2: Creating API key..."
# Create API key using st2 CLI
API_KEY=$(docker exec stackstorm-api st2 apikey create -k -t "$TOKEN" 2>/dev/null | grep -o '[a-f0-9]\{64\}' | head -1)

if [ -z "$API_KEY" ]; then
    echo ""
    echo "ERROR: Failed to create API key"
    echo ""
    echo "Troubleshooting:"
    echo "  docker logs stackstorm-api"
    echo "  docker exec stackstorm-api st2 apikey create -k -t \"$TOKEN\""
    exit 1
fi

echo "✓ API key created successfully"
echo ""

echo "Step 3: Updating .env file..."
# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Update or add ST2_API_KEY in .env
if grep -q "^ST2_API_KEY=" .env; then
    # Update existing line (works on both Linux and macOS)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^ST2_API_KEY=.*/ST2_API_KEY=$API_KEY/" .env
    else
        sed -i "s/^ST2_API_KEY=.*/ST2_API_KEY=$API_KEY/" .env
    fi
    echo "✓ Updated existing ST2_API_KEY in .env"
else
    # Add new line
    echo "ST2_API_KEY=$API_KEY" >> .env
    echo "✓ Added ST2_API_KEY to .env"
fi

echo ""
echo "Step 4: Restarting PoundCake services..."
docker compose restart api oven timer

# Wait a moment for services to restart
sleep 3

echo ""
echo "========================================"
echo "✓ Configuration Complete!"
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
echo "Create your first recipe:"
echo "  curl -X POST http://localhost:8000/api/recipes/ \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d @examples/recipe-hostdown.json"
echo ""

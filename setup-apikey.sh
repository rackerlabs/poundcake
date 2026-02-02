#!/bin/bash
# Generate StackStorm API Key and Update .env
# This script automates the API key generation process

set -e

echo "========================================"
echo "StackStorm API Key Generator"
echo "========================================"
echo ""

# Check if docker compose is running
if ! docker compose ps | grep -q "stackstorm-api.*running"; then
    echo "ERROR: StackStorm API is not running"
    echo "Please start services first: docker compose up -d"
    exit 1
fi

if ! docker compose ps | grep -q "stackstorm-auth.*running"; then
    echo "ERROR: StackStorm Auth is not running"
    echo "Please start services first: docker compose up -d"
    exit 1
fi

echo "Step 1: Authenticating with StackStorm..."
# Get authentication token
TOKEN=$(docker exec stackstorm-auth st2 auth st2admin -p Ch@ngeMe -t 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to authenticate"
    echo "Please ensure StackStorm services are running and credentials are correct"
    exit 1
fi

echo "✓ Authentication successful"
echo ""

echo "Step 2: Creating API key..."
# Create API key using st2 CLI
API_KEY=$(docker exec stackstorm-api st2 apikey create -k -t "$TOKEN" 2>/dev/null | grep -o '[a-f0-9]\{64\}' | head -1)

if [ -z "$API_KEY" ]; then
    echo "ERROR: Failed to create API key"
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
    # Update existing line
    sed -i.bak "s/^ST2_API_KEY=.*/ST2_API_KEY=$API_KEY/" .env
    echo "✓ Updated existing ST2_API_KEY in .env"
else
    # Add new line
    echo "ST2_API_KEY=$API_KEY" >> .env
    echo "✓ Added ST2_API_KEY to .env"
fi

echo ""
echo "Step 4: Restarting PoundCake services..."
docker compose restart api oven timer

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
echo "You can verify the setup with:"
echo "  docker compose ps"
echo "  curl http://localhost:8000/api/v1/health"
echo ""

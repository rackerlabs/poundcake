#!/bin/bash
# ST2 API Key Auto-Generation Script
# This script generates a StackStorm API key and updates .env file

set -e

echo "========================================" 
echo "StackStorm API Key Auto-Generator"
echo "========================================"
echo ""

echo "Waiting for StackStorm services..."
MAX_WAIT=60
WAITED=0

# Wait for ST2 API to be available
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://stackstorm-api:9101/v1 2>&1 | grep -q "faultstring"; then
        echo "✓ StackStorm API is responding"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: StackStorm API did not become available"
    exit 1
fi

# Wait for ST2 Auth to be available
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://stackstorm-auth:9100/v1 2>&1 | grep -q "faultstring\|auth"; then
        echo "✓ StackStorm Auth is responding"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: StackStorm Auth did not become available"
    exit 1
fi

echo ""
echo "Authenticating with StackStorm..."

# Get authentication token using st2 CLI
TOKEN=$(curl -s -X POST http://stackstorm-auth:9100/v1/auth/tokens \
    -H "Content-Type: application/json" \
    -d '{"username": "st2admin", "password": "Ch@ngeMe"}' | \
    grep -o '"token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to authenticate with StackStorm"
    exit 1
fi

echo "✓ Authentication successful"
echo ""
echo "Creating API key..."

# Create API key using the token
API_KEY=$(curl -s -X POST http://stackstorm-api:9101/v1/apikeys \
    -H "Content-Type: application/json" \
    -H "X-Auth-Token: $TOKEN" \
    -d '{"user": "st2admin"}' | \
    grep -o '"key":"[^"]*"' | cut -d'"' -f4)

if [ -z "$API_KEY" ]; then
    echo "ERROR: Failed to create API key"
    exit 1
fi

echo "✓ API key created successfully"
echo ""

# Update .env file
if [ -f "/poundcake/.env" ]; then
    echo "Updating /poundcake/.env file..."
    
    if grep -q "^ST2_API_KEY=" /poundcake/.env; then
        # Update existing line
        sed -i "s/^ST2_API_KEY=.*/ST2_API_KEY=$API_KEY/" /poundcake/.env
        echo "✓ Updated existing ST2_API_KEY"
    else
        # Add new line
        echo "ST2_API_KEY=$API_KEY" >> /poundcake/.env
        echo "✓ Added ST2_API_KEY"
    fi
else
    echo "ERROR: /poundcake/.env not found"
    exit 1
fi

echo ""
echo "========================================"
echo "✓ API Key Setup Complete!"
echo "========================================"
echo ""
echo "API Key: $API_KEY"
echo ""
echo "Restarting PoundCake services to apply key..."

# Signal services to restart by touching a flag file
touch /poundcake/.env.updated

echo "Complete! PoundCake services will pick up the new key."


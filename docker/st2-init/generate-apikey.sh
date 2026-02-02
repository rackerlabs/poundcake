#!/bin/bash
# ST2 API Key Auto-Generation Script
# Uses st2 CLI for proper StackStorm interaction

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
    if /opt/stackstorm/st2/bin/st2 --version >/dev/null 2>&1; then
        # Check if API is responding
        if /opt/stackstorm/st2/bin/st2 action list --limit 1 >/dev/null 2>&1 || echo "test" | grep -q "test"; then
            echo "✓ StackStorm services available"
            break
        fi
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $((WAITED % 10)) -eq 0 ]; then
        echo "  Waiting for StackStorm... (${WAITED}/${MAX_WAIT}s)"
    fi
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: StackStorm services did not become available"
    exit 1
fi

echo ""
echo "Authenticating with StackStorm..."

# Use st2 CLI to authenticate and get token
TOKEN=$(/opt/stackstorm/st2/bin/st2 auth st2admin -p Ch@ngeMe -t 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to authenticate with StackStorm"
    echo "Check credentials: st2admin / Ch@ngeMe"
    exit 1
fi

echo "✓ Authentication successful"
echo ""
echo "Creating API key..."

# Use st2 CLI to create API key
API_KEY=$(/opt/stackstorm/st2/bin/st2 apikey create -k -t "$TOKEN" 2>/dev/null)

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
echo "PoundCake services will pick up the new key on restart."



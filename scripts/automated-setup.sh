#!/bin/bash
set -e

echo "========================================="
echo "  PoundCake StackStorm Setup"
echo "========================================="

# Create config directory if it doesn't exist
mkdir -p /app/config

# Check if API key already exists
if [ -f "/app/config/st2_api_key" ]; then
    EXISTING_KEY=$(cat /app/config/st2_api_key)
    if [ -n "$EXISTING_KEY" ]; then
        echo "✓ StackStorm API key already exists: $EXISTING_KEY"
        echo "Skipping key generation"
        exit 0
    fi
fi

# Wait for StackStorm API to be ready
MAX_RETRIES=30
RETRY_INTERVAL=5
RETRY_COUNT=0

echo "Waiting for StackStorm API to be ready..."

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -sf http://stackstorm-api:9101/v1/actions?limit=1 >/dev/null 2>&1; then
        echo "✓ StackStorm API is ready"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Attempt $RETRY_COUNT/$MAX_RETRIES: StackStorm not ready yet, waiting ${RETRY_INTERVAL}s..."
    sleep $RETRY_INTERVAL
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "✗ Timed out waiting for StackStorm API"
    exit 1
fi

# Additional wait to ensure StackStorm is fully initialized
echo "Waiting additional 10 seconds for StackStorm to fully initialize..."
sleep 10

# Create API key using st2 CLI
echo "Creating StackStorm API key..."

# Authenticate and get token
ST2_TOKEN=$(st2 auth st2admin -p 'Ch@ngeMe' -t 2>&1 || echo "")

if [ -z "$ST2_TOKEN" ]; then
    echo "✗ Failed to authenticate with StackStorm"
    exit 1
fi

echo "✓ Authenticated with StackStorm"

# Create API key
API_KEY=$(st2 apikey create -k -u st2admin -p 'Ch@ngeMe' 2>&1 | grep -oP '(?<=key: )\S+' || echo "")

if [ -z "$API_KEY" ]; then
    echo "✗ Failed to create API key"
    exit 1
fi

echo "✓ API key created: $API_KEY"

# Write to config file (this will be read at runtime)
echo "$API_KEY" > /app/config/st2_api_key
chmod 644 /app/config/st2_api_key

echo "✓ API key written to /app/config/st2_api_key"

# Also update .env for reference (if mounted)
if [ -f "/app/.env" ]; then
    if grep -q "^ST2_API_KEY=" /app/.env; then
        sed -i "s|^ST2_API_KEY=.*|ST2_API_KEY=$API_KEY|" /app/.env
        echo "✓ Updated ST2_API_KEY in .env file"
    else
        echo "ST2_API_KEY=$API_KEY" >> /app/.env
        echo "✓ Added ST2_API_KEY to .env file"
    fi
fi

echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "StackStorm API Key: $API_KEY"
echo ""
echo "The API will read this key automatically from:"
echo "  /app/config/st2_api_key"
echo ""
echo "No restart required - key is loaded at runtime!"
echo ""

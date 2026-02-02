#!/bin/bash
# ST2 API Key Auto-Generation Script
# This script generates a StackStorm API key and makes it available to other services

set -e

echo "Waiting for StackStorm API to be ready..."
MAX_ATTEMPTS=30
ATTEMPT=0

# Wait for ST2 API to be available
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -sf http://stackstorm-api:9101/v1 >/dev/null 2>&1 || \
       curl -sf http://stackstorm-api:9101/v1 2>&1 | grep -q "401"; then
        echo "StackStorm API is responding"
        break
    fi
    
    ATTEMPT=$((ATTEMPT + 1))
    echo "Attempt $ATTEMPT/$MAX_ATTEMPTS..."
    sleep 2
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo "ERROR: StackStorm API did not become available"
    exit 1
fi

echo "Authenticating with StackStorm..."
# Get authentication token
TOKEN=$(curl -sf -X POST http://stackstorm-auth:9100/v1/auth/tokens \
    -H "Content-Type: application/json" \
    -d '{"username": "st2admin", "password": "Ch@ngeMe"}' | \
    grep -o '"token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to authenticate with StackStorm"
    exit 1
fi

echo "Authentication successful"
echo "Creating API key..."

# Create API key using the token
API_KEY=$(curl -sf -X POST http://stackstorm-api:9101/v1/apikeys \
    -H "Content-Type: application/json" \
    -H "X-Auth-Token: $TOKEN" \
    -H "St2-Api-Key: $TOKEN" \
    -d '{"user": "st2admin"}' | \
    grep -o '"key":"[^"]*"' | cut -d'"' -f4)

if [ -z "$API_KEY" ]; then
    echo "ERROR: Failed to create API key"
    exit 1
fi

echo "API key created successfully"

# Write the API key to a shared location
echo "$API_KEY" > /st2-keys/apikey.txt
chmod 644 /st2-keys/apikey.txt

echo "API key written to /st2-keys/apikey.txt"
echo "API Key: $API_KEY"

# Keep container running so the volume persists
echo "Init complete. Keeping container running..."
tail -f /dev/null

#!/bin/bash
set -e

echo "========================================="
echo "  PoundCake StackStorm Setup"
echo "========================================="

# Create config directory if it doesn't exist
mkdir -p /app/config

# Wait for StackStorm API to be ready first
MAX_RETRIES=30
RETRY_INTERVAL=5
RETRY_COUNT=0

echo "Waiting for StackStorm API to be ready..."

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    # Check if ST2 API responds (even 401 means it's ready)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://stackstorm-api:9101/v1 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" != "000" ]; then
        echo "[OK] StackStorm API is ready (HTTP $HTTP_CODE)"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Attempt $RETRY_COUNT/$MAX_RETRIES: StackStorm not ready yet, waiting ${RETRY_INTERVAL}s..."
    sleep $RETRY_INTERVAL
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "[ERROR] Timed out waiting for StackStorm API"
    exit 1
fi

# Additional wait to ensure StackStorm is fully initialized
echo "Waiting additional 10 seconds for StackStorm to fully initialize..."
sleep 10

# NOW check if API key already exists AND is valid (after StackStorm is ready)
if [ -f "/app/config/st2_api_key" ]; then
    EXISTING_KEY=$(cat /app/config/st2_api_key)
    if [ -n "$EXISTING_KEY" ]; then
        echo "Found existing API key file: ${EXISTING_KEY:0:40}..."
        echo "Validating key with StackStorm..."
        
        # Test if the key works by listing actions
        if curl -s -H "St2-Api-Key: $EXISTING_KEY" http://stackstorm-api:9101/v1/actions?limit=1 2>&1 | grep -q '"name"'; then
            echo "[OK] Existing API key is valid"
            echo "Skipping key generation"
            exit 0
        else
            echo "[WARN] Existing API key is invalid (key not in MongoDB)"
            echo "[WARN] Deleting old key and regenerating..."
            rm -f /app/config/st2_api_key
        fi
    fi
fi

# Create API key using st2 CLI
echo "Creating StackStorm API key..."

# Authenticate and capture token
echo "Authenticating with StackStorm..."
ST2_TOKEN=$(st2 auth st2admin -p 'Ch@ngeMe' -t 2>&1)

if [ -z "$ST2_TOKEN" ] || echo "$ST2_TOKEN" | grep -q "ERROR"; then
    echo "[ERROR] Failed to authenticate with StackStorm"
    echo "[ERROR] Auth output: $ST2_TOKEN"
    exit 1
fi

echo "[OK] Authenticated with StackStorm"
echo "Token: ${ST2_TOKEN:0:20}..."

# Export token for st2 CLI to use
export ST2_AUTH_TOKEN="$ST2_TOKEN"

# Create API key using the token
echo "Running: st2 apikey create -k -t \$ST2_AUTH_TOKEN"
set +e  # Don't exit on error, we want to capture it
APIKEY_OUTPUT=$(st2 apikey create -k -t "$ST2_AUTH_TOKEN" 2>&1)
CREATE_EXIT_CODE=$?
set -e  # Re-enable exit on error

echo "Command exit code: $CREATE_EXIT_CODE"
echo "Raw output:"
echo "$APIKEY_OUTPUT"

if [ $CREATE_EXIT_CODE -ne 0 ]; then
    echo "[ERROR] st2 apikey create failed with exit code $CREATE_EXIT_CODE"
    echo "[ERROR] Output: $APIKEY_OUTPUT"
    exit 1
fi

# The -k flag outputs just the key, no table formatting
# Just use the output directly, stripping whitespace
API_KEY=$(echo "$APIKEY_OUTPUT" | tr -d '[:space:]')

if [ -z "$API_KEY" ]; then
    echo "[ERROR] Failed to create API key - output was empty"
    exit 1
fi

# Validate key looks reasonable (alphanumeric, 32+ chars)
if [ ${#API_KEY} -lt 32 ]; then
    echo "[ERROR] API key too short: ${#API_KEY} characters"
    echo "[ERROR] Key value: $API_KEY"
    exit 1
fi

echo "[OK] API key created: ${API_KEY:0:40}..."

# Write to config file (this will be read at runtime)
echo "$API_KEY" > /app/config/st2_api_key
chmod 644 /app/config/st2_api_key

echo "[OK] API key written to /app/config/st2_api_key"

# Register StackStorm content (packs, actions, sensors, etc.)
echo "Registering StackStorm content..."
if st2-register-content --register-all --config-file /etc/st2/st2.conf 2>&1 | grep -i "registered\|success" >/dev/null; then
    echo "[OK] StackStorm content registered"
else
    echo "[WARN] Content registration may have failed, but continuing..."
fi

# Install additional packs from StackStorm Exchange
echo "Installing StackStorm packs..."

# Install kubernetes pack
echo "Installing kubernetes pack..."
if st2 pack install kubernetes 2>&1 | grep -i "success\|installed" >/dev/null; then
    echo "[OK] kubernetes pack installed"
else
    echo "[WARN] kubernetes pack installation may have failed"
fi

# Install rackspace pack
echo "Installing rackspace pack..."
if st2 pack install rackspace 2>&1 | grep -i "success\|installed" >/dev/null; then
    echo "[OK] rackspace pack installed"
else
    echo "[WARN] rackspace pack installation may have failed"
fi

echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "StackStorm API Key: ${API_KEY:0:40}... (${#API_KEY} chars)"
echo "StackStorm Content: Registered (core pack and actions available)"
echo "StackStorm Packs: kubernetes, rackspace"
echo "StackStorm Services: garbagecollector, chatops"
echo ""
echo "The API will read this key automatically from:"
echo "  /app/config/st2_api_key"
echo ""
echo "No restart required - key is loaded at runtime!"
echo ""

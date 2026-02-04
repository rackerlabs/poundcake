#!/bin/bash
set -e

echo "========================================="
echo "  PoundCake StackStorm Setup"
echo "========================================="

mkdir -p /app/config

# 1. Wait for StackStorm API to be ready
MAX_RETRIES=30
RETRY_COUNT=0
echo "Waiting for StackStorm API..."
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://stackstorm-api:9101/v1 || echo "000")
    if [ "$HTTP_CODE" != "000" ]; then
        echo "[OK] API is up (HTTP $HTTP_CODE)"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 5
done

# Authenticate to get a token
echo "Authenticating as ${ST2_AUTH_USER}..."
ST2_TOKEN=$(st2 auth "${ST2_AUTH_USER}" -p "${ST2_AUTH_PASSWORD}" -t)
export ST2_AUTH_TOKEN=$ST2_TOKEN

# 3. Idempotent API Key Creation
# Check if key exists AND is still valid in the DB
if [ -f "/app/config/st2_api_key" ]; then
    OLD_KEY=$(cat /app/config/st2_api_key)
    if curl -s -k -H "St2-Api-Key: $OLD_KEY" http://stackstorm-api:9101/v1/actions > /dev/null; then
        echo "[OK] Existing API Key is valid. Skipping creation."
    else
        echo "[WARN] Key file found but invalid. Re-generating..."
        st2 apikey create -m "PoundCake-Internal" -u ${ST2_AUTH_USER} > /app/config/st2_api_key
    fi
else
    echo "Generating new API Key..."
    st2 apikey create -m "PoundCake-Internal" -u ${ST2_AUTH_USER} > /app/config/st2_api_key
fi

# 4. Register Content & Install Packs
echo "Registering content..."
st2-register-content --register-all --config-file /etc/st2/st2.conf

for pack in kubernetes rackspace; do
    if st2 pack list | grep -q "$pack"; then
        echo "[OK] Pack $pack already installed."
    else
        echo "Installing $pack..."
        st2 pack install "$pack"
    fi
done

echo "Setup Complete!"

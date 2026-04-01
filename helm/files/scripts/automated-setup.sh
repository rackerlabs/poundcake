#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
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
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ]; then
        echo "[OK] API endpoint reachable (HTTP $HTTP_CODE)"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 5
done
if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "[ERROR] StackStorm API did not become reachable."
    exit 1
fi

# Authenticate to get a token (retry until available)
echo "Authenticating as ${ST2_AUTH_USER}..."
AUTH_RETRIES=30
AUTH_COUNT=0
ST2_TOKEN=""
while [ $AUTH_COUNT -lt $AUTH_RETRIES ]; do
    set +e
    AUTH_OUTPUT=$(st2 auth "${ST2_AUTH_USER}" -p "${ST2_AUTH_PASSWORD}" -t 2>&1)
    AUTH_RC=$?
    set -e
    if [ "$AUTH_RC" -eq 0 ]; then
        TOKEN_CANDIDATE=$(echo "$AUTH_OUTPUT" | tr -d '\r\n')
        if echo "$TOKEN_CANDIDATE" | grep -Eq '^[A-Za-z0-9._-]{20,}$'; then
            ST2_TOKEN="$TOKEN_CANDIDATE"
        else
            echo "[WARN] st2 auth returned non-token output, retrying..."
            ST2_TOKEN=""
        fi
    else
        echo "[WARN] st2 auth failed (exit $AUTH_RC), retrying..."
        ST2_TOKEN=""
    fi
    if [ -n "$ST2_TOKEN" ]; then
        export ST2_AUTH_TOKEN=$ST2_TOKEN
        # Verify the token works by making a test API call
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Auth-Token: $ST2_TOKEN" http://stackstorm-api:9101/v1/actions || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "[OK] Authentication successful and verified (HTTP $HTTP_CODE)"
            break
        else
            echo "[WARN] Token rejected by API (HTTP $HTTP_CODE), retrying..."
            ST2_TOKEN=""
        fi
    fi
    AUTH_COUNT=$((AUTH_COUNT + 1))
    sleep 4
done
if [ -z "$ST2_TOKEN" ]; then
    echo "[ERROR] Failed to authenticate to StackStorm API."
    exit 1
fi

create_api_key() {
    local key
    # Retry the API key creation with exponential backoff
    for attempt in 1 2 3 4 5; do
        key=$(st2 apikey create -k -m '{"description": "PoundCake-Internal"}' 2>/dev/null || true)
        if [ -n "$key" ] && [[ "$key" != ERROR:* ]]; then
            echo "$key"
            return 0
        fi
        # Wait longer between retries to allow token to propagate
        sleep $((attempt * 2))
    done
    return 1
}

# 3. Idempotent API Key Creation
# Check if key exists AND is still valid in the DB
if [ -f "/app/config/st2_api_key" ] && [ -s "/app/config/st2_api_key" ]; then
    OLD_KEY=$(cat /app/config/st2_api_key)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k -H "St2-Api-Key: $OLD_KEY" http://stackstorm-api:9101/v1/actions || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "[OK] Existing API Key is valid. Skipping creation."
    else
        echo "[WARN] Key file found but invalid (HTTP $HTTP_CODE). Re-generating..."
        KEY_RETRIES=20
        KEY_COUNT=0
        while [ $KEY_COUNT -lt $KEY_RETRIES ]; do
            if NEW_KEY=$(create_api_key); then
                echo "$NEW_KEY" > /app/config/st2_api_key
                break
            fi
            KEY_COUNT=$((KEY_COUNT + 1))
            sleep 4
        done
        if [ ! -s "/app/config/st2_api_key" ]; then
            echo "[ERROR] Failed to generate API key."
            exit 1
        fi
    fi
else
    echo "Generating new API Key..."
    KEY_RETRIES=20
    KEY_COUNT=0
    while [ $KEY_COUNT -lt $KEY_RETRIES ]; do
        if NEW_KEY=$(create_api_key); then
            echo "$NEW_KEY" > /app/config/st2_api_key
            break
        fi
        KEY_COUNT=$((KEY_COUNT + 1))
        sleep 4
    done
    if [ ! -s "/app/config/st2_api_key" ]; then
        echo "[ERROR] Failed to generate API key."
        exit 1
    fi
fi

# 4. Register built-in content before pack installs so pack-management actions exist.
echo "Registering content..."
st2-register-content --register-all --config-file /tmp/st2/st2.conf

# 5. Install enabled third-party packs after the API is up, authenticated, and initial content exists.
if [ "${ST2_INSTALL_KUBERNETES_PACK:-false}" = "true" ] || [ "${ST2_INSTALL_OPENSTACK_PACK:-false}" = "true" ]; then
    echo "Installing enabled third-party packs..."
    /bin/bash /install-third-party-packs.sh
fi

echo ""
echo "========================================="
echo "  Verifying Core Components"
echo "========================================="

# Verify core pack is available
if st2 action list --pack=core > /dev/null 2>&1; then
    echo "[OK] Core pack verified and functional"
    echo ""
    echo "Sample core actions:"
    st2 action list --pack=core | head -5
else
    echo "[ERROR] Core pack not available or not functional!"
    echo "This is a critical issue - PoundCake requires core pack."
    exit 1
fi

echo ""
echo "All registered packs:"
st2 pack list

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "Note: Additional packs can be installed later using StackStorm client tools."
echo "      The kubernetes and openstack packs are installed by"
echo "      stackstorm-bootstrap when enabled via stackstorm.bootstrap.packs.<pack>.enabled."
echo "      Manual install examples:"
echo "      Helm/Kubernetes:"
echo "      kubectl -n <namespace> exec -it deploy/stackstorm-client -- st2 pack install <pack-name>"
echo "      Docker Compose:"
echo "      docker compose -f docker/docker-compose.yml exec st2client st2 pack install <pack-name>"
echo ""

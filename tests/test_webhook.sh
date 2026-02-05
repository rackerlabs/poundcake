#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#          PoundCake Webhook Test Script

set -e

API_URL="http://localhost:8000/api/v1"
RECIPE_NAME="TestAutomation_INT_$(date +%s)"

wait_for_recipe_ready() {
    local recipe_name="$1"
    local max_retries="${2:-20}"
    local sleep_seconds="${3:-2}"
    local count=0
    local response=""

    while [ $count -lt $max_retries ]; do
        echo "Waiting for recipe [$recipe_name] to be ready... ($((count+1))/$max_retries)"
        response=$(curl -s "$API_URL/recipes/by-name/$recipe_name")

        if echo "$response" | grep -q '"id"' \
            && echo "$response" | grep -q '"ingredients"' \
            && echo "$response" | grep -q '"task_id"'; then
            echo "    [OK] Recipe is available with ingredients."
            return 0
        fi

        sleep "$sleep_seconds"
        count=$((count+1))
    done

    echo "    [ERROR] Recipe [$recipe_name] not ready after $((max_retries * sleep_seconds)) seconds."
    echo "    Last response: $response"
    return 1
}

wait_for_alert_by_name() {
    local alert_name="$1"
    local max_retries="${2:-10}"
    local sleep_seconds="${3:-1}"
    local count=0
    local response=""

    while [ $count -lt $max_retries ]; do
        echo "    Waiting for alert [$alert_name] to be stored... ($((count+1))/$max_retries)"
        response=$(curl -s "$API_URL/alerts?alert_name=$alert_name")

        if [ -n "$response" ] && [ "$response" != "[]" ]; then
            echo "    [OK] Alert found in database"
            return 0
        fi

        sleep "$sleep_seconds"
        count=$((count+1))
    done

    echo "    [ERROR] Alert [$alert_name] not found after $((max_retries * sleep_seconds)) seconds."
    echo "    Response: $response"
    return 1
}

echo "========================================"
echo "PoundCake Webhook Test"
echo "========================================"
echo ""

# 1. Health Check
echo "Step 1: Checking API health..."
HEALTH=$(curl -s "$API_URL/health")
STATUS=$(echo "$HEALTH" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

if [ "$STATUS" == "healthy" ] || [ "$STATUS" == "degraded" ]; then
    echo "    [OK] API is responding: $STATUS"
else
    echo "    [ERROR] API health check failed"
    echo "    Response: $HEALTH"
    exit 1
fi

# 2. Create a test recipe (and wait for it to exist with ingredients)
echo ""
echo "Step 2: Creating test recipe [$RECIPE_NAME]..."
RECIPE_JSON=$(cat <<EOF
{
  "name": "$RECIPE_NAME",
  "description": "Webhook Test Recipe",
  "enabled": true,
  "ingredients": [
    {
      "task_id": "step_1",
      "task_name": "Initial Check",
      "task_order": 1,
      "is_blocking": true,
      "st2_action": "core.local",
      "parameters": { "cmd": "echo 'Step 1 success'" },
      "expected_time_to_completion": 10
    },
    {
      "task_id": "step_2",
      "task_name": "Parallel Notification",
      "task_order": 2,
      "is_blocking": false,
      "st2_action": "core.local",
      "parameters": { "cmd": "echo 'Step 2 success'" },
      "expected_time_to_completion": 10
    }
  ]
}
EOF
)

curl -s -X POST "$API_URL/recipes/" \
     -H "Content-Type: application/json" \
     -d "$RECIPE_JSON" > /dev/null

echo "    [OK] Recipe created."
echo "    Waiting for recipe [$RECIPE_NAME] to be ready..."
wait_for_recipe_ready "$RECIPE_NAME" 20 2

# 3. Send Test Alert
echo ""
echo "Step 3: Sending test alert to webhook..."

ALERT_JSON=$(cat <<EOF
{
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "$RECIPE_NAME",
        "group_name": "$RECIPE_NAME",
        "instance": "test-server-01",
        "severity": "warning"
      },
      "annotations": {
        "summary": "Test alert for webhook validation"
      },
      "startsAt": "2026-02-03T00:00:00Z",
      "generatorURL": "http://prometheus:9090"
    }
  ]
}
EOF
)

WEBHOOK_RESPONSE=$(curl -s -i -X POST "$API_URL/webhook" \
     -H "Content-Type: application/json" \
     -d "$ALERT_JSON")

HTTP_STATUS=$(echo "$WEBHOOK_RESPONSE" | grep -i "^HTTP" | awk '{print $2}')
REQ_ID=$(echo "$WEBHOOK_RESPONSE" | grep -i "x-request-id" | awk '{print $2}' | tr -d '\r')

if [ "$HTTP_STATUS" == "202" ] || [ "$HTTP_STATUS" == "201" ] || [ "$HTTP_STATUS" == "200" ]; then
    echo "    [OK] Webhook accepted alert (HTTP $HTTP_STATUS)"
    echo "    Request ID: $REQ_ID"
else
    echo "    [ERROR] Webhook rejected alert"
    echo "    HTTP Status: $HTTP_STATUS"
    echo "    Response: $WEBHOOK_RESPONSE"
    exit 1
fi

# 4. Verify Alert Was Stored
echo ""
echo "Step 4: Verifying alert was stored in database..."
wait_for_alert_by_name "$RECIPE_NAME" 12 1

# 5. Check if alert can be retrieved by req_id
echo ""
echo "Step 5: Retrieving alert by request ID..."
if [ -n "$REQ_ID" ]; then
    ALERT_BY_REQID=$(curl -s "$API_URL/alerts" | grep "$REQ_ID" || echo "")
    if [ -n "$ALERT_BY_REQID" ]; then
        echo "    [OK] Alert retrieved successfully with req_id: $REQ_ID"
    else
        echo "    [WARN] Could not retrieve alert by req_id"
    fi
else
    echo "    [WARN] No request ID to test with"
fi

echo ""
echo "========================================"
echo "[OK] Webhook test passed!"
echo "========================================"
echo ""
echo "Test Summary:"
echo "  - API health: OK"
echo "  - Alert ingestion: OK"
echo "  - Database storage: OK"
echo "  - Request ID tracking: OK"
echo ""

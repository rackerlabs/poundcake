#!/bin/bash
# PoundCake End-to-End Flow Test
# Tests: Recipe Creation -> Alert Intake -> Oven Baking -> Execution Tracking

set -e

# Configuration
API_URL="http://localhost:8000/api/v1"
RECIPE_NAME="TestAutomation_$(date +%s)"

wait_for_recipe_ready() {
    local recipe_name="$1"
    local max_retries="${2:-20}"
    local sleep_seconds="${3:-2}"
    local count=0
    local response=""

    while [ $count -lt $max_retries ]; do
        echo "Waiting for recipe [$recipe_name] to be ready... ($((count+1))/$max_retries)"
        response=$(curl -s "$API_URL/recipes/name/$recipe_name")

        if echo "$response" | grep -q '"id"' \
            && echo "$response" | grep -q '"ingredients"' \
            && echo "$response" | grep -q '"task_id"'; then
            echo "OK: Recipe is available with ingredients."
            return 0
        fi

        sleep "$sleep_seconds"
        count=$((count+1))
    done

    echo "ERROR: Recipe [$recipe_name] not ready after $((max_retries * sleep_seconds)) seconds."
    echo "Last response: $response"
    return 1
}

echo "-------------------------------------------------------"
echo "Starting PoundCake End-to-End Test"
echo "-------------------------------------------------------"

# 1. Create a Multi-Step Recipe
echo "Step 1: Creating a test recipe [$RECIPE_NAME]..."
RECIPE_JSON=$(cat <<EOF
{
  "name": "$RECIPE_NAME",
  "description": "E2E Test Recipe",
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

echo "OK: Recipe created."
wait_for_recipe_ready "$RECIPE_NAME" 20 2

# 2. Fire a Mock Alert
echo "Step 2: Firing mock Alertmanager webhook..."
ALERT_JSON=$(cat <<EOF
{
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "$RECIPE_NAME",
        "instance": "test-host-01",
        "severity": "critical"
      },
      "annotations": {
        "summary": "Test alert for PoundCake"
      },
      "startsAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    }
  ]
}
EOF
)

# Capture the X-Request-ID from the response headers
RESPONSE=$(curl -s -i -X POST "$API_URL/webhook" \
     -H "Content-Type: application/json" \
     -d "$ALERT_JSON")

REQ_ID=$(echo "$RESPONSE" | grep -i x-request-id | awk '{print $2}' | tr -d '\r')

if [ -z "$REQ_ID" ]; then
    echo "ERROR: Failed to retrieve X-Request-ID from API."
    exit 1
fi

echo "OK: Alert accepted. Trace ID: $REQ_ID"

# 3. Poll for Oven Creation and Execution
echo "Step 3: Monitoring task progression..."
echo "Waiting for Oven Dispatcher to bake tasks..."

MAX_RETRIES=12
COUNT=0

while [ $COUNT -lt $MAX_RETRIES ]; do
    echo "Checking status... ($((COUNT+1))/$MAX_RETRIES)"

    # Fetch ovens for this request ID
    OVENS=$(curl -s "$API_URL/ovens?req_id=$REQ_ID")

    # Check if we got a valid response
    if [ -z "$OVENS" ] || [ "$OVENS" == "[]" ]; then
        echo "WAIT: No ovens found yet..."
    else
        # Count total tasks and completed tasks
        TOTAL=$(echo "$OVENS" | jq '. | length')
        PROCESSING=$(echo "$OVENS" | jq '[.[] | select(.processing_status=="processing")] | length')
        COMPLETE=$(echo "$OVENS" | jq '[.[] | select(.processing_status=="complete")] | length')

        echo "STATUS: $TOTAL tasks found | $PROCESSING processing | $COMPLETE complete"

        if [ "$COMPLETE" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
            echo ""
            echo "-------------------------------------------------------"
            echo "SUCCESS: All tasks for $REQ_ID have finished!"
            echo "-------------------------------------------------------"
            exit 0
        fi
    fi

    sleep 5
    COUNT=$((COUNT+1))
done

echo "FAILURE: Test timed out. Check logs with: docker compose logs | grep $REQ_ID"
exit 1

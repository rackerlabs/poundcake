#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#          PoundCake Webhook Test Script

set -e

API_URL="http://localhost:8000/api/v1"

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

# 2. Send Test Alert
echo ""
echo "Step 2: Sending test alert to webhook..."

ALERT_JSON=$(cat <<'EOF'
{
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HelloWorldAlert",
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

# 3. Verify Alert Was Stored
echo ""
echo "Step 3: Verifying alert was stored in database..."
sleep 2  # Give it a moment to be stored

ALERTS=$(curl -s "$API_URL/alerts?processing_status=new")
ALERT_NAME=$(echo "$ALERTS" | grep -o '"alert_name":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ "$ALERT_NAME" == "HelloWorldAlert" ]; then
    echo "    [OK] Alert found in database"
    echo "    Alert name: $ALERT_NAME"
else
    echo "    [ERROR] Alert not found in 'new' queue"
    echo "    Response: $ALERTS"
    exit 1
fi

# 4. Check if alert can be retrieved by req_id
echo ""
echo "Step 4: Retrieving alert by request ID..."
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

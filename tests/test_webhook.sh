#!/bin/bashQ
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#

API_URL="http://localhost:8000"

echo "PoundCake API - Quick Webhook Test"
echo "===================================="
echo "Testing endpoint: $API_URL/api/v1/webhook"
echo ""

echo "1. Checking API health..."
HEALTH=$(curl -s "$API_URL/api/v1/health")
STATUS=$(echo "$HEALTH" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
if [ "$STATUS" == "healthy" ]; then
    echo "   ✓ API is healthy"
else
    echo "   ✗ API is not healthy"
    echo "$HEALTH"
    exit 1
fi
echo ""

echo "2. Sending Hello World alert..."
RESPONSE=$(curl -s -X POST "$API_URL/api/v1/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-group",
    "status": "firing",
    "receiver": "poundcake",
    "groupLabels": {"alertname": "HelloWorldAlert"},
    "commonLabels": {"alertname": "HelloWorldAlert"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "HelloWorldAlert",
        "severity": "info",
        "instance": "test-server:8080"
      },
      "annotations": {
        "summary": "Hello World Test Alert",
        "description": "Testing the PoundCake API webhook endpoint"
      },
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "hello-world-test-12345"
    }]
  }')

WEBHOOK_STATUS=$(echo "$RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
ALERTS_RECEIVED=$(echo "$RESPONSE" | grep -o '"alerts_received":[0-9]*' | cut -d':' -f2)
REQ_ID=$(echo "$RESPONSE" | grep -o '"request_id":"[^"]*"' | cut -d'"' -f4)

if [ "$WEBHOOK_STATUS" == "accepted" ]; then
    echo "   ✓ Alert accepted!"
    echo "   - Status: $WEBHOOK_STATUS"
    echo "   - Alerts received: $ALERTS_RECEIVED"
    echo "   - Request ID: $REQ_ID"
else
    echo "   ✗ Alert rejected"
    echo "$RESPONSE"
    exit 1
fi
echo ""

echo "3. Waiting for alert processing (5 seconds)..."
sleep 5
echo ""

echo "4. Checking alert was stored..."
# Use query parameter instead of path parameter
ALERT_CHECK=$(curl -s "$API_URL/api/v1/alerts?fingerprint=hello-world-test-12345")
ALERT_NAME=$(echo "$ALERT_CHECK" | grep -o '"alert_name":"[^"]*"' | cut -d'"' -f4)
PROCESSING_STATUS=$(echo "$ALERT_CHECK" | grep -o '"processing_status":"[^"]*"' | cut -d'"' -f4)

if [ -n "$ALERT_NAME" ]; then
    echo "   ✓ Alert stored in database!"
    echo "   - Alert name: $ALERT_NAME"
    echo "   - Processing status: $PROCESSING_STATUS"
    echo "   - Request ID: $REQ_ID"
else
    echo "   ✗ Alert not found in database"
    exit 1
fi
echo ""

echo "===================================="
echo "✓ All tests passed!"
echo ""

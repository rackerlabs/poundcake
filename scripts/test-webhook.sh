#!/bin/bash
# Quick test script for PoundCake API webhook

set -e

API_URL="${API_URL:-http://localhost:8000}"
WEBHOOK_ENDPOINT="$API_URL/api/v1/webhook"

echo "PoundCake API - Quick Webhook Test"
echo "===================================="
echo ""
echo "Testing endpoint: $WEBHOOK_ENDPOINT"
echo ""

# Test 1: Health check
echo "1. Checking API health..."
HEALTH_RESPONSE=$(curl -s "$API_URL/api/v1/health")
HEALTH_STATUS=$(echo "$HEALTH_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

if [ "$HEALTH_STATUS" = "healthy" ]; then
    echo "   ✓ API is healthy"
else
    echo "   ✗ API is unhealthy: $HEALTH_RESPONSE"
    exit 1
fi
echo ""

# Test 2: Send hello world alert
echo "2. Sending Hello World alert..."
ALERT_RESPONSE=$(curl -s -X POST "$WEBHOOK_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"HelloWorldAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "HelloWorldAlert"},
    "commonLabels": {"alertname": "HelloWorldAlert", "severity": "info"},
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

ALERT_STATUS=$(echo "$ALERT_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
ALERTS_RECEIVED=$(echo "$ALERT_RESPONSE" | grep -o '"alerts_received":[0-9]*' | cut -d':' -f2)
REQUEST_ID=$(echo "$ALERT_RESPONSE" | grep -o '"request_id":"[^"]*"' | cut -d'"' -f4)

if [ "$ALERT_STATUS" = "accepted" ]; then
    echo "   ✓ Alert accepted!"
    echo "   - Status: $ALERT_STATUS"
    echo "   - Alerts received: $ALERTS_RECEIVED"
    echo "   - Request ID: $REQUEST_ID"
else
    echo "   ✗ Alert not accepted: $ALERT_RESPONSE"
    exit 1
fi
echo ""

# Test 3: Wait for processing
echo "3. Waiting for alert processing (5 seconds)..."
sleep 5
echo ""

# Test 4: Check alert was stored
echo "4. Checking alert was stored..."
ALERT_CHECK=$(curl -s "$API_URL/api/v1/alerts/hello-world-test-12345")
ALERT_NAME=$(echo "$ALERT_CHECK" | grep -o '"alert_name":"[^"]*"' | cut -d'"' -f4)
PROCESSING_STATUS=$(echo "$ALERT_CHECK" | grep -o '"processing_status":"[^"]*"' | cut -d'"' -f4)

if [ -n "$ALERT_NAME" ]; then
    echo "   ✓ Alert found in database!"
    echo "   - Alert name: $ALERT_NAME"
    echo "   - Processing status: $PROCESSING_STATUS"
else
    echo "   ✗ Alert not found in database"
    exit 1
fi
echo ""

# Test 5: Check statistics
echo "5. Checking system statistics..."
STATS=$(curl -s "$API_URL/api/v1/stats")
TOTAL_ALERTS=$(echo "$STATS" | grep -o '"total_alerts":[0-9]*' | cut -d':' -f2)
TOTAL_API_CALLS=$(echo "$STATS" | grep -o '"total_api_calls":[0-9]*' | cut -d':' -f2)

echo "   ✓ Statistics retrieved"
echo "   - Total alerts: $TOTAL_ALERTS"
echo "   - Total API calls: $TOTAL_API_CALLS"
echo ""

# Success
echo "===================================="
echo "✓ All tests passed!"
echo ""
echo "Next steps:"
echo "  - View Flower dashboard: http://localhost:5555"
echo "  - List all alerts: curl $API_URL/api/v1/alerts"
echo "  - Check logs: docker-compose logs -f worker"
echo ""

#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Assert order status for a given request ID
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
REQ_ID=${REQ_ID:-}
EXPECTED_STATUS=${EXPECTED_STATUS:-}

if [ -z "$REQ_ID" ] || [ -z "$EXPECTED_STATUS" ]; then
  echo "REQ_ID and EXPECTED_STATUS are required"
  exit 1
fi

order=$(curl -sS "${API_URL}/orders?req_id=${REQ_ID}" | jq -r '.[0]')
status=$(echo "$order" | jq -r '.processing_status')

if [ "$status" != "$EXPECTED_STATUS" ]; then
  echo "Expected order status ${EXPECTED_STATUS}, got ${status}"
  exit 1
fi

echo "Order status OK: ${status}"

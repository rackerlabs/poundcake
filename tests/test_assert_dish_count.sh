#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Assert dish count for a given request ID
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
REQ_ID=${REQ_ID:-}
EXPECTED_COUNT=${EXPECTED_COUNT:-}

if [ -z "$REQ_ID" ] || [ -z "$EXPECTED_COUNT" ]; then
  echo "REQ_ID and EXPECTED_COUNT are required"
  exit 1
fi

count=$(curl -sS "${API_URL}/dishes?req_id=${REQ_ID}" | jq -r 'length')

if [ "$count" != "$EXPECTED_COUNT" ]; then
  echo "Expected ${EXPECTED_COUNT} dishes, got ${count}"
  exit 1
fi

echo "Dish count OK: ${count}"

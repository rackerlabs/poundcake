#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Fetch dishes for a given request ID or order ID
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
REQ_ID=${REQ_ID:-}
ORDER_ID=${ORDER_ID:-}

if [ -z "$REQ_ID" ] && [ -z "$ORDER_ID" ]; then
  echo "REQ_ID or ORDER_ID is required"
  exit 1
fi

if [ -n "$REQ_ID" ]; then
  curl -sS "${API_URL}/dishes?req_id=${REQ_ID}" | jq
else
  curl -sS "${API_URL}/dishes?order_id=${ORDER_ID}" | jq
fi

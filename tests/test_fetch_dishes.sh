#!/usr/bin/env bash
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

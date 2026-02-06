#!/usr/bin/env bash
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
REQ_ID=${REQ_ID:-}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-30}
INTERVAL=${INTERVAL:-2}

if [ -z "$REQ_ID" ]; then
  echo "REQ_ID is required"
  exit 1
fi

start=$(date +%s)

echo "Waiting for dishes with req_id=${REQ_ID}"

while true; do
  dishes=$(curl -sS "${API_URL}/dishes?req_id=${REQ_ID}")
  count=$(echo "$dishes" | jq -r 'length')
  if [ "$count" != "0" ]; then
    echo "$dishes" | jq
    exit 0
  fi

  now=$(date +%s)
  if [ $((now - start)) -ge "$TIMEOUT_SECONDS" ]; then
    echo "Timed out waiting for dishes"
    exit 1
  fi
  sleep "$INTERVAL"
 done

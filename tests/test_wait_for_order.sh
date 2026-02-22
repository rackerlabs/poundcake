#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Wait for dishes to be created for a given request ID
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

REQ_ID=${REQ_ID:-}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-$TEST_TIMEOUT_SEC}
INTERVAL=${INTERVAL:-$POLL_INTERVAL_SEC}

require_cmd curl
require_cmd jq

if [ -z "$REQ_ID" ]; then
  echo "REQ_ID is required"
  exit 1
fi

start=$(date +%s)

log_info "Waiting for order with req_id=${REQ_ID}"

while true; do
  orders=$(api_request_json GET "${API_URL}/orders?req_id=${REQ_ID}")
  count=$(echo "$orders" | jq -r 'length')
  if [ "$count" != "0" ]; then
    echo "$orders" | jq -r '.[0]'
    exit 0
  fi

  now=$(date +%s)
  if [ $((now - start)) -ge "$TIMEOUT_SECONDS" ]; then
    log_error "Timed out waiting for order"
    exit 1
  fi
  sleep "$INTERVAL"
 done

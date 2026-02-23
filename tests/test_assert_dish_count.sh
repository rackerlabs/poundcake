#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Assert dish count for a given request ID
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

REQ_ID=${REQ_ID:-}
EXPECTED_COUNT=${EXPECTED_COUNT:-}

require_cmd curl
require_cmd jq

if [ -z "$REQ_ID" ] || [ -z "$EXPECTED_COUNT" ]; then
  echo "REQ_ID and EXPECTED_COUNT are required"
  exit 1
fi

count=$(api_request_json GET "${API_URL}/dishes?req_id=${REQ_ID}" | jq -r 'length')

if [ "$count" != "$EXPECTED_COUNT" ]; then
  log_error "Expected ${EXPECTED_COUNT} dishes, got ${count}"
  exit 1
fi

log_info "Dish count OK: ${count}"

#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Post an order for a given recipe and request ID
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

TEST_RECIPE=${TEST_RECIPE:-}
REQ_ID=${REQ_ID:-}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

require_cmd curl
require_cmd jq

# Verify the recipe exists before posting order
log_info "Checking if recipe exists: ${TEST_RECIPE}"
RECIPE_EXISTS=$(api_request_json GET "${API_URL}/recipes/?name=${TEST_RECIPE}" | jq -r 'length')

if [ "$RECIPE_EXISTS" -eq 0 ]; then
  log_error "Recipe '${TEST_RECIPE}' does not exist"
  log_info "Available recipes:"
  api_request_json GET "${API_URL}/recipes/" | jq -r '.[].name'
  exit 1
fi

log_info "Recipe found: ${TEST_RECIPE}"

if [ -z "$REQ_ID" ]; then
  REQ_ID="AUTOMATED-$(date +%s)"
fi

payload=$(cat <<JSON
{
  "req_id": "${REQ_ID}",
  "fingerprint": "AutomatedTestAlert_localhost:9090",
  "alert_status": "firing",
  "processing_status": "new",
  "alert_group_name": "${TEST_RECIPE}",
  "severity": "warning",
  "instance": "localhost:9090",
  "labels": {
    "alertname": "AutomatedTestAlert",
    "group_name": "${TEST_RECIPE}",
    "severity": "warning",
    "instance": "localhost:9090"
  },
  "annotations": {
    "summary": "Automated manual order test"
  },
  "raw_data": {
    "status": "firing",
    "labels": {
      "alertname": "AutomatedTestAlert",
      "group_name": "${TEST_RECIPE}",
      "severity": "warning",
      "instance": "localhost:9090"
    },
    "annotations": {
      "summary": "Automated manual order test"
    },
    "startsAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "endsAt": null,
    "generatorURL": "http://prometheus:9090/graph"
  },
  "starts_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "ends_at": null
}
JSON
)

log_info "Posting manual order for recipe: ${TEST_RECIPE}"
REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/orders" "${payload}" >/dev/null
echo "REQ_ID=${REQ_ID}"

#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Post a webhook to create an order for a given recipe and request ID
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

# Verify the recipe exists before posting webhook
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
  "receiver": "poundcake",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "AutomatedTestAlert",
        "group_name": "${TEST_RECIPE}",
        "severity": "warning",
        "instance": "localhost:9090"
      },
      "annotations": {
        "summary": "Automated webhook test"
      },
      "startsAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
      "endsAt": null,
      "generatorURL": "http://prometheus:9090/graph"
    }
  ],
  "groupLabels": {
    "alertname": "AutomatedTestAlert"
  },
  "commonLabels": {
    "alertname": "AutomatedTestAlert",
    "group_name": "${TEST_RECIPE}"
  },
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "version": "4",
  "groupKey": "{}:{alertname=\"AutomatedTestAlert\"}"
}
JSON
)

log_info "Posting webhook for recipe: ${TEST_RECIPE}"
REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/webhook" "${payload}" >/dev/null
echo "REQ_ID=${REQ_ID}"

#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Post a webhook to create an order for a given recipe and request ID
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
TEST_RECIPE=${TEST_RECIPE:-}
REQ_ID=${REQ_ID:-}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

# Verify the recipe exists before posting webhook
echo "Checking if recipe exists: ${TEST_RECIPE}"
RECIPE_EXISTS=$(curl -sS -X GET "${API_URL}/recipes/?name=${TEST_RECIPE}" | jq -r 'length')

if [ "$RECIPE_EXISTS" -eq 0 ]; then
  echo "Error: Recipe '${TEST_RECIPE}' does not exist!"
  echo "Available recipes:"
  curl -sS -X GET "${API_URL}/recipes/" | jq -r '.[].name'
  exit 1
fi

echo "Recipe found: ${TEST_RECIPE}"

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

echo "Posting webhook for recipe: ${TEST_RECIPE}"

curl -sS -X POST "${API_URL}/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: ${REQ_ID}" \
  -d "${payload}"

echo
echo "REQ_ID=${REQ_ID}"

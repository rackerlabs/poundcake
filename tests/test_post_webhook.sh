#!/usr/bin/env bash
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
TEST_RECIPE=${TEST_RECIPE:-}
REQ_ID=${REQ_ID:-}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

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

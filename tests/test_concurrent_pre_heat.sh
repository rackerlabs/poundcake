#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Concurrent webhook posts should increment counter on a single active order
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
TEST_RECIPE=${TEST_RECIPE:-"concurrent-preheat-$(date +%s)"}
REQ_ID=${REQ_ID:-"CONCURRENT-PREHEAT-$(date +%s)"}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-20}
INTERVAL=${INTERVAL:-1}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

payload=$(jq -n \
  --arg group_name "$TEST_RECIPE" \
  '{
    receiver: "poundcake",
    status: "firing",
    alerts: [
      {
        status: "firing",
        labels: {
          alertname: "ConcurrentPreheatTest",
          group_name: $group_name,
          severity: "warning",
          instance: "localhost:9090"
        },
        annotations: {summary: "Concurrent pre-heat test"},
        startsAt: (now | todateiso8601),
        endsAt: null,
        generatorURL: "http://prometheus:9090/graph"
      }
    ],
    groupLabels: {alertname: "ConcurrentPreheatTest"},
    commonLabels: {alertname: "ConcurrentPreheatTest", group_name: $group_name},
    commonAnnotations: {},
    externalURL: "http://alertmanager:9093",
    version: "4",
    groupKey: "{}:{alertname=\"ConcurrentPreheatTest\"}"
  }')

curl -sS -X POST "${API_URL}/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: ${REQ_ID}-A" \
  -d "${payload}" >/dev/null &
curl -sS -X POST "${API_URL}/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: ${REQ_ID}-B" \
  -d "${payload}" >/dev/null &
wait

start=$(date +%s)
while true; do
  orders=$(curl -sS "${API_URL}/orders?alert_group_name=${TEST_RECIPE}")
  active=$(echo "$orders" | jq '[.[] | select(.is_active == true)]')
  active_count=$(echo "$active" | jq -r 'length')
  counter=$(echo "$active" | jq -r '.[0].counter // 0')

  if [ "$active_count" = "1" ] && [ "$counter" -ge 2 ]; then
    echo "$active" | jq
    exit 0
  fi

  now=$(date +%s)
  if [ $((now - start)) -ge "$TIMEOUT_SECONDS" ]; then
    echo "Timed out waiting for counter increment"
    echo "Active count: ${active_count}, counter: ${counter}"
    echo "$orders" | jq
    exit 1
  fi
  sleep "$INTERVAL"
done

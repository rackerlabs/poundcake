#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Concurrent webhook posts should increment counter on a single active order
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

TEST_RECIPE=${TEST_RECIPE:-"concurrent-preheat-$(date +%s)"}
REQ_ID=${REQ_ID:-"CONCURRENT-PREHEAT-$(date +%s)"}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-$TEST_TIMEOUT_SEC}
INTERVAL=${INTERVAL:-$POLL_INTERVAL_SEC}

require_cmd curl
require_cmd jq

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

REQUEST_ID="${REQ_ID}-A" api_request_json POST "${API_URL}/webhook" "${payload}" >/dev/null &
REQUEST_ID="${REQ_ID}-B" api_request_json POST "${API_URL}/webhook" "${payload}" >/dev/null &
wait

start=$(date +%s)
while true; do
  orders=$(api_request_json GET "${API_URL}/orders?alert_group_name=${TEST_RECIPE}")
  active=$(echo "$orders" | jq '[.[] | select(.is_active == true)]')
  active_count=$(echo "$active" | jq -r 'length')
  counter=$(echo "$active" | jq -r '.[0].counter // 0')

  if [ "$active_count" = "1" ] && [ "$counter" -ge 2 ]; then
    echo "$active" | jq
    exit 0
  fi

  now=$(date +%s)
  if [ $((now - start)) -ge "$TIMEOUT_SECONDS" ]; then
    log_error "Timed out waiting for counter increment"
    log_error "Active count: ${active_count}, counter: ${counter}"
    echo "$orders" | jq
    exit 1
  fi
  sleep "$INTERVAL"
done

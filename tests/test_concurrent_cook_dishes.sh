#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Concurrent cook_dishes requests should create exactly one dish
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

TEST_RECIPE=${TEST_RECIPE:-"concurrent-cook-$(date +%s)"}
REQ_ID=${REQ_ID:-"CONCURRENT-COOK-$(date +%s)"}

require_cmd curl
require_cmd jq

log_info "Creating recipe: ${TEST_RECIPE}"
TEST_RECIPE="${TEST_RECIPE}" IS_BLOCKING=true \
  "${SCRIPT_DIR}/test_create_recipe_single_step.sh" >/dev/null

payload=$(jq -n \
  --arg req_id "$REQ_ID" \
  --arg group_name "$TEST_RECIPE" \
  '{
    req_id: $req_id,
    fingerprint: ("concurrent-cook-" + $req_id),
    alert_status: "firing",
    processing_status: "new",
    alert_group_name: $group_name,
    severity: "warning",
    instance: "localhost:9090",
    labels: {
      alertname: "ConcurrentCookTest",
      group_name: $group_name,
      severity: "warning",
      instance: "localhost:9090"
    },
    annotations: {summary: "Concurrent cook test"},
    raw_data: {
      status: "firing",
      labels: {
        alertname: "ConcurrentCookTest",
        group_name: $group_name,
        severity: "warning",
        instance: "localhost:9090"
      },
      annotations: {summary: "Concurrent cook test"},
      startsAt: (now | todateiso8601),
      endsAt: null,
      generatorURL: "http://prometheus:9090/graph"
    },
    starts_at: (now | todateiso8601),
    ends_at: null
  }')

order=$(REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/orders" "${payload}")

order_id=$(echo "$order" | jq -r '.id')
if [ -z "$order_id" ] || [ "$order_id" = "null" ]; then
  echo "Failed to create order"
  echo "$order" | jq
  exit 1
fi

log_info "Order created: ${order_id}"

REQUEST_ID="${REQ_ID}-A" api_request_json POST "${API_URL}/dishes/cook/${order_id}" >/dev/null &
REQUEST_ID="${REQ_ID}-B" api_request_json POST "${API_URL}/dishes/cook/${order_id}" >/dev/null &
wait

dishes=$(api_request_json GET "${API_URL}/dishes?order_id=${order_id}")
count=$(echo "$dishes" | jq -r 'length')

log_info "Dish count for order ${order_id}: ${count}"
echo "$dishes" | jq

if [ "$count" != "1" ]; then
  log_error "Expected exactly 1 dish, got ${count}"
  exit 1
fi

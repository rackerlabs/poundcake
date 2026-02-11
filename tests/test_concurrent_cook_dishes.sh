#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Concurrent cook_dishes requests should create exactly one dish
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
TEST_RECIPE=${TEST_RECIPE:-"concurrent-cook-$(date +%s)"}
REQ_ID=${REQ_ID:-"CONCURRENT-COOK-$(date +%s)"}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

echo "Creating recipe: ${TEST_RECIPE}"
TEST_RECIPE="${TEST_RECIPE}" IS_BLOCKING=true \
  /Users/chris.breu/code/poundcake/tests/test_create_recipe_single_step.sh >/dev/null

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

order=$(curl -sS -X POST "${API_URL}/orders" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: ${REQ_ID}" \
  -d "${payload}")

order_id=$(echo "$order" | jq -r '.id')
if [ -z "$order_id" ] || [ "$order_id" = "null" ]; then
  echo "Failed to create order"
  echo "$order" | jq
  exit 1
fi

echo "Order created: ${order_id}"

curl -sS -X POST "${API_URL}/dishes/cook/${order_id}" \
  -H "X-Request-ID: ${REQ_ID}-A" >/dev/null &
curl -sS -X POST "${API_URL}/dishes/cook/${order_id}" \
  -H "X-Request-ID: ${REQ_ID}-B" >/dev/null &
wait

dishes=$(curl -sS "${API_URL}/dishes?order_id=${order_id}")
count=$(echo "$dishes" | jq -r 'length')

echo "Dish count for order ${order_id}: ${count}"
echo "$dishes" | jq

if [ "$count" != "1" ]; then
  echo "Expected exactly 1 dish, got ${count}"
  exit 1
fi

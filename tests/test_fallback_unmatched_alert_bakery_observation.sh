#!/usr/bin/env bash
# Observe fallback behavior when no recipe matches an alert group and show Bakery call shape.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"
start_test_target
register_cleanup_trap

require_cmd jq
require_cmd curl

TEST_TS=${TEST_TS:-$(date +%s)}
REQ_ID=${REQ_ID:-"FALLBACK-OBS-${TEST_TS}"}
UNMATCHED_GROUP=${UNMATCHED_GROUP:-"no-recipe-match-${TEST_TS}"}

log_info "Creating unmatched order (group=${UNMATCHED_GROUP}, req_id=${REQ_ID})"
order_payload=$(jq -n \
  --arg req_id "${REQ_ID}" \
  --arg group_name "${UNMATCHED_GROUP}" \
  '{
    req_id: $req_id,
    fingerprint: ("fallback-observe-" + $req_id),
    alert_status: "firing",
    processing_status: "new",
    alert_group_name: $group_name,
    severity: "warning",
    instance: "localhost:9090",
    labels: {
      alertname: "FallbackObserveTest",
      group_name: $group_name,
      severity: "warning",
      instance: "localhost:9090"
    },
    annotations: {summary: "Observe fallback Bakery call path", description: "Observe fallback Bakery call path end to end."},
    raw_data: {
      status: "firing",
      labels: {
        alertname: "FallbackObserveTest",
        group_name: $group_name,
        severity: "warning",
        instance: "localhost:9090"
      },
      annotations: {summary: "Observe fallback Bakery call path", description: "Observe fallback Bakery call path end to end."},
      startsAt: (now | todateiso8601),
      endsAt: null
    },
    starts_at: (now | todateiso8601),
    ends_at: null
  }')

order_json=$(REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/orders" "${order_payload}")
order_id=$(echo "${order_json}" | jq -r '.id')
if [ -z "${order_id}" ] || [ "${order_id}" = "null" ]; then
  log_error "Failed to create order"
  echo "${order_json}" | jq >&2
  exit 1
fi

log_info "Dispatch firing phase for order_id=${order_id}"
REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/orders/${order_id}/dispatch" >/dev/null

dishes_json=$(api_request_json GET "${API_URL}/dishes?order_id=${order_id}")
firing_dish_id=$(echo "${dishes_json}" | jq -r '[.[] | select(.run_phase=="firing")] | first | .id // empty')
if [ -z "${firing_dish_id}" ]; then
  log_error "No firing dish created for order_id=${order_id}"
  echo "${dishes_json}" | jq >&2
  exit 1
fi

# Force terminalization so API runs Bakery sync/comment logic now, independent of workers.
log_info "Mark firing dish complete to trigger terminal sync paths (dish_id=${firing_dish_id})"
api_request_json PUT "${API_URL}/dishes/${firing_dish_id}" '{"processing_status":"complete","execution_status":"succeeded"}' >/dev/null

order_after_firing=$(api_request_json GET "${API_URL}/orders/${order_id}")
ticket_id=$(echo "${order_after_firing}" | jq -r '.bakery_ticket_id // empty')
ticket_state=$(echo "${order_after_firing}" | jq -r '.bakery_ticket_state // empty')
last_error=$(echo "${order_after_firing}" | jq -r '.bakery_last_error // empty')

log_info "Order Bakery state after firing terminalization:"
echo "${order_after_firing}" | jq '{id, processing_status, is_active, bakery_ticket_id, bakery_ticket_state, bakery_operation_id, bakery_last_error}'

log_info "Move order to resolving and dispatch resolving phase"
api_request_json PUT "${API_URL}/orders/${order_id}" '{"processing_status":"resolving","alert_status":"resolved"}' >/dev/null
dispatch_resolve=$(REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/orders/${order_id}/dispatch")
echo "${dispatch_resolve}" | jq

resolving_dish_id=$(echo "${dispatch_resolve}" | jq -r '.dish_id // empty')
if [ -z "${resolving_dish_id}" ]; then
  log_error "No resolving dish returned by dispatch"
  exit 1
fi

ingredients_json=$(api_request_json GET "${API_URL}/dishes/${resolving_dish_id}/ingredients")
bakery_row=$(echo "${ingredients_json}" | jq -c '[.[] | select((.execution_engine // "") == "bakery")] | first')
if [ -z "${bakery_row}" ] || [ "${bakery_row}" = "null" ]; then
  log_error "No Bakery ingredient found in resolving dish"
  echo "${ingredients_json}" | jq >&2
  exit 1
fi

operation=$(echo "${bakery_row}" | jq -r '.execution_parameters.operation // empty')
recipe_ingredient_id=$(echo "${bakery_row}" | jq -r '.recipe_ingredient_id // empty')

case "${operation}" in
  ticket_create) expected_call="POST /api/v1/communications" ;;
  ticket_update) expected_call="PATCH /api/v1/communications/{communication_id}" ;;
  ticket_comment) expected_call="POST /api/v1/communications/{communication_id}/notifications" ;;
  ticket_close) expected_call="POST /api/v1/communications/{communication_id}/close" ;;
  *) expected_call="UNKNOWN (operation=${operation})" ;;
esac

log_info "Resolved Bakery operation mapping from seeded fallback ingredient:"
echo "${bakery_row}" | jq '{execution_target, execution_parameters, execution_payload}'
echo "expected_remote_bakery_call=${expected_call}"

execute_payload=$(jq -n \
  --arg target "$(echo "${bakery_row}" | jq -r '.execution_target')" \
  --argjson payload "$(echo "${bakery_row}" | jq -c '.execution_payload // {}')" \
  --argjson parameters "$(echo "${bakery_row}" | jq -c '.execution_parameters // {}')" \
  --argjson order_id "${order_id}" \
  --argjson recipe_ingredient_id "${recipe_ingredient_id:-0}" \
  --arg ticket_id "${ticket_id}" \
  '{
    execution_engine: "bakery",
    execution_target: $target,
    execution_payload: $payload,
    execution_parameters: $parameters,
    context: {
      order_id: $order_id,
      recipe_ingredient_id: $recipe_ingredient_id,
      bakery_ticket_id: ($ticket_id | select(length > 0))
    }
  }')

log_info "Calling /cook/execute with seeded resolving Bakery row to observe response"
execute_resp=$(REQUEST_ID="${REQ_ID}" api_request_json POST "${API_URL}/cook/execute" "${execute_payload}")
echo "${execute_resp}" | jq

if [ -n "${last_error}" ]; then
  log_warn "Bakery sync last_error after firing phase: ${last_error}"
fi
if [ -z "${ticket_id}" ]; then
  log_warn "No bakery_ticket_id found on order; remote ticket operations may fail validation."
fi
if [ -n "${ticket_state}" ]; then
  log_info "Current bakery_ticket_state=${ticket_state}"
fi

log_info "Fallback unmatched-alert Bakery observation script complete."

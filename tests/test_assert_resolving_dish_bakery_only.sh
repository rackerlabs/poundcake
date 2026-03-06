#!/usr/bin/env bash
# Assert resolving-phase dish includes only Bakery ingredients and no StackStorm rows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

REQ_ID=${REQ_ID:-}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-$TEST_TIMEOUT_SEC}
INTERVAL=${INTERVAL:-$POLL_INTERVAL_SEC}

require_cmd curl
require_cmd jq

if [ -z "${REQ_ID}" ]; then
  log_error "REQ_ID is required"
  exit 1
fi

start=$(date +%s)
resolving_dish=""
while true; do
  dishes=$(api_request_json GET "${API_URL}/dishes?req_id=${REQ_ID}")
  resolving_dish=$(echo "${dishes}" | jq -cr '[.[] | select(.run_phase=="resolving")] | sort_by(.created_at) | last // empty')
  if [ -n "${resolving_dish}" ]; then
    break
  fi

  now=$(date +%s)
  if [ $((now - start)) -ge "${TIMEOUT_SECONDS}" ]; then
    log_error "Timed out waiting for resolving dish for req_id=${REQ_ID}"
    echo "${dishes}" | jq >&2
    exit 1
  fi
  sleep "${INTERVAL}"
done

resolving_dish_id=$(echo "${resolving_dish}" | jq -r '.id')
ingredients=$(api_request_json GET "${API_URL}/dishes/${resolving_dish_id}/ingredients")

stackstorm_count=$(echo "${ingredients}" | jq -r '[.[] | select((.execution_engine // "") == "stackstorm")] | length')
if [ "${stackstorm_count}" != "0" ]; then
  log_error "Resolving dish contains StackStorm ingredients; expected none"
  echo "${ingredients}" | jq >&2
  exit 1
fi

bakery_count=$(echo "${ingredients}" | jq -r '[.[] | select((.execution_engine // "") == "bakery")] | length')
if [ "${bakery_count}" -lt 1 ]; then
  log_error "Resolving dish does not contain Bakery ingredient rows"
  echo "${ingredients}" | jq >&2
  exit 1
fi

log_info "Resolving dish assertion OK: dish_id=${resolving_dish_id}, bakery_rows=${bakery_count}"

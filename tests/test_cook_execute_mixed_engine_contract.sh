#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

require_cmd jq
require_cmd curl

STACKSTORM_PAYLOAD=$(jq -n '{
  execution_engine: "stackstorm",
  execution_target: "poundcake.nonexistent",
  execution_parameters: {}
}')

BAKERY_PAYLOAD=$(jq -n '{
  execution_engine: "bakery",
  execution_target: "tickets.create",
  execution_payload: {title: "mixed", description: "mixed"}
}')

STACKSTORM_RESP=$(api_request_json POST "${API_URL}/cook/execute" "${STACKSTORM_PAYLOAD}")
BAKERY_RESP=$(api_request_json POST "${API_URL}/cook/execute" "${BAKERY_PAYLOAD}")

echo "${STACKSTORM_RESP}" | jq -e '.engine == "stackstorm" and (.status | IN("queued","running","succeeded","failed","canceled"))'
echo "${BAKERY_RESP}" | jq -e '.engine == "bakery" and (.status | IN("queued","running","succeeded","failed","canceled"))'

log_info "Mixed-engine /cook/execute contract verified"

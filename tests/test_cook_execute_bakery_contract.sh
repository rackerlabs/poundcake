#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

require_cmd jq
require_cmd curl

REQUEST_PAYLOAD=$(jq -n '{
  execution_engine: "bakery",
  execution_target: "core",
  execution_parameters: {
    operation: "ticket_create"
  },
  execution_payload: {
    title: "Codex shell contract test",
    description: "Validate unified execute response envelope"
  }
}')

RESPONSE=$(api_request_json POST "${API_URL}/cook/execute" "${REQUEST_PAYLOAD}")

echo "${RESPONSE}" | jq -e '
  .engine == "bakery" and
  (.status | IN("queued","running","succeeded","failed","canceled")) and
  has("execution_ref") and
  has("error_message") and
  has("result") and
  has("raw") and
  has("attempts")
'

log_info "Bakery /cook/execute canonical contract verified"

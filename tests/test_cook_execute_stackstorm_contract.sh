#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

require_cmd jq
require_cmd curl

REQUEST_PAYLOAD=$(jq -n '{
  execution_engine: "stackstorm",
  execution_target: "poundcake.this_action_probably_does_not_exist",
  execution_parameters: {}
}')

RESPONSE=$(api_request_json POST "${API_URL}/cook/execute" "${REQUEST_PAYLOAD}")

echo "${RESPONSE}" | jq -e '
  .engine == "stackstorm" and
  (.status | IN("queued","running","succeeded","failed","canceled")) and
  has("execution_ref") and
  has("error_message") and
  has("result") and
  has("raw") and
  has("attempts")
'

log_info "StackStorm /cook/execute canonical contract verified"

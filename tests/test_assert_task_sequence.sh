#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Assert two-step task sequence semantics from dish.result task timestamps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

REQ_ID=${REQ_ID:-}
ASSERT_MODE=${ASSERT_MODE:-blocking}
NON_BLOCKING_TOLERANCE_SEC=${NON_BLOCKING_TOLERANCE_SEC:-1}

require_cmd curl
require_cmd jq

if [ -z "${REQ_ID}" ]; then
  log_error "REQ_ID is required"
  exit 1
fi

if [ "${ASSERT_MODE}" != "blocking" ] && [ "${ASSERT_MODE}" != "non_blocking" ]; then
  log_error "ASSERT_MODE must be one of: blocking, non_blocking"
  exit 1
fi

normalize_timestamp() {
  local ts="$1"
  local base frac
  if [[ "${ts}" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.([0-9]+))?Z$ ]]; then
    base="${BASH_REMATCH[1]}"
    frac="${BASH_REMATCH[3]:-0}"
    frac="${frac}000000"
    frac="${frac:0:6}"
    printf "%s.%sZ" "${base}" "${frac}"
    return 0
  fi

  log_error "Invalid timestamp format: ${ts}"
  return 1
}

to_epoch_seconds() {
  local ts="$1"
  echo "${ts}" | jq -r 'sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601'
}

dishes=$(api_request_json GET "${API_URL}/dishes?req_id=${REQ_ID}")

if [ "$(echo "${dishes}" | jq -r 'length')" -eq 0 ]; then
  log_error "No dishes found for req_id=${REQ_ID}"
  exit 1
fi

dish=$(echo "${dishes}" | jq -cr 'sort_by(.created_at) | last')

tasks=$(echo "${dish}" | jq -cer '
  if (.result | type) == "array" then
    .result
  elif (.result | type) == "object" and (.result.tasks | type) == "array" then
    .result.tasks
  else
    []
  end
')

if [ "$(echo "${tasks}" | jq -r 'length')" -lt 2 ]; then
  log_error "Expected at least two task entries in dish.result"
  echo "${tasks}" | jq
  exit 1
fi

step_1=$(echo "${tasks}" | jq -cr 'map(select((.task_id // "") | test("^step_1_"))) | sort_by(.start_timestamp // .end_timestamp // "") | .[0]')
step_2=$(echo "${tasks}" | jq -cr 'map(select((.task_id // "") | test("^step_2_"))) | sort_by(.start_timestamp // .end_timestamp // "") | .[0]')

if [ -z "${step_1}" ] || [ "${step_1}" = "null" ] || [ -z "${step_2}" ] || [ "${step_2}" = "null" ]; then
  log_error "Could not find both step_1_* and step_2_* task entries in dish.result"
  echo "${tasks}" | jq
  exit 1
fi

step_1_task_id=$(echo "${step_1}" | jq -r '.task_id // empty')
step_1_start=$(echo "${step_1}" | jq -r '.start_timestamp // empty')
step_1_end=$(echo "${step_1}" | jq -r '.end_timestamp // empty')
step_2_task_id=$(echo "${step_2}" | jq -r '.task_id // empty')
step_2_start=$(echo "${step_2}" | jq -r '.start_timestamp // empty')

if [ -z "${step_1_start}" ] || [ -z "${step_1_end}" ] || [ -z "${step_2_start}" ]; then
  log_error "Missing required timestamps for step sequence assertion"
  echo "${tasks}" | jq
  exit 1
fi

step_1_start_norm=$(normalize_timestamp "${step_1_start}")
step_1_end_norm=$(normalize_timestamp "${step_1_end}")
step_2_start_norm=$(normalize_timestamp "${step_2_start}")
step_1_start_epoch=$(to_epoch_seconds "${step_1_start_norm}")
step_2_start_epoch=$(to_epoch_seconds "${step_2_start_norm}")

log_info "Sequence check mode=${ASSERT_MODE}"
log_info "step_1=${step_1_task_id} start=${step_1_start_norm} end=${step_1_end_norm}"
log_info "step_2=${step_2_task_id} start=${step_2_start_norm}"

if [ "${ASSERT_MODE}" = "blocking" ]; then
  if [[ "${step_2_start_norm}" < "${step_1_end_norm}" ]]; then
    log_error "Blocking assertion failed: step_2 started before step_1 completed"
    exit 1
  fi
  log_info "Blocking assertion passed: step_2 starts at/after step_1 completion"
  exit 0
fi

if [[ "${step_2_start_norm}" < "${step_1_end_norm}" ]]; then
  log_info "Non-blocking assertion passed: step_2 overlaps with step_1"
  exit 0
fi

if [ $((step_2_start_epoch - step_1_start_epoch)) -le "${NON_BLOCKING_TOLERANCE_SEC}" ]; then
  log_info "Non-blocking assertion passed: step starts were near-simultaneous"
  exit 0
fi

log_error "Non-blocking assertion failed: step_2 did not start before step_1 completed"
exit 1

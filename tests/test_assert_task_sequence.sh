#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Assert two-step task sequence semantics from task execution timestamps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

REQ_ID=${REQ_ID:-}
ASSERT_MODE=${ASSERT_MODE:-blocking}
NON_BLOCKING_TOLERANCE_SEC=${NON_BLOCKING_TOLERANCE_SEC:-1}
TASK_TIMESTAMP_TIMEOUT_SEC=${TASK_TIMESTAMP_TIMEOUT_SEC:-30}
TASK_TIMESTAMP_POLL_INTERVAL_SEC=${TASK_TIMESTAMP_POLL_INTERVAL_SEC:-2}

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

  if [[ "${ts}" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.([0-9]+))?\+00:00$ ]]; then
    base="${BASH_REMATCH[1]}"
    frac="${BASH_REMATCH[3]:-0}"
    frac="${frac}000000"
    frac="${frac:0:6}"
    printf "%s.%sZ" "${base}" "${frac}"
    return 0
  fi

  if [[ "${ts}" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.([0-9]+))?$ ]]; then
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
  jq -rn --arg ts "${ts}" '$ts | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601'
}

is_valid_json() {
  local payload="$1"
  echo "${payload}" | jq -e . >/dev/null 2>&1
}

dishes=$(api_request_json GET "${API_URL}/dishes?req_id=${REQ_ID}")

if [ "$(echo "${dishes}" | jq -r 'length')" -eq 0 ]; then
  log_error "No dishes found for req_id=${REQ_ID}"
  exit 1
fi

dish=$(echo "${dishes}" | jq -cr 'sort_by(.created_at) | last')
dish_id=$(echo "${dish}" | jq -r '.id')

build_tasks_payload() {
  local dish_json="$1"
  local from_result from_ingredients
  from_result=$(echo "${dish_json}" | jq -cer '
    if (.result | type) == "array" then
      .result
    elif (.result | type) == "object" and (.result.tasks | type) == "array" then
      .result.tasks
    else
      []
    end
  ')

  if [ "$(echo "${from_result}" | jq -r 'length')" -ge 2 ]; then
    echo "${from_result}"
    return 0
  fi

  from_ingredients=$(api_request_json GET "${API_URL}/dishes/${dish_id}/ingredients")
  echo "${from_ingredients}" | jq -cer '
    map({
      task_key: .task_key,
      execution_ref: .execution_ref,
      execution_status: .execution_status,
      start_timestamp: .started_at,
      end_timestamp: .completed_at
    })
  '
}

wait_for_task_starts() {
  local deadline now tasks_local started_count dishes_local dish_local
  deadline=$(( $(date +%s) + TASK_TIMESTAMP_TIMEOUT_SEC ))
  tasks_local='[]'
  while true; do
    dishes_local=$(api_request_json GET "${API_URL}/dishes?req_id=${REQ_ID}")
    if ! is_valid_json "${dishes_local}"; then
      sleep "${TASK_TIMESTAMP_POLL_INTERVAL_SEC}"
      continue
    fi

    if [ "$(echo "${dishes_local}" | jq -r 'length')" -eq 0 ]; then
      sleep "${TASK_TIMESTAMP_POLL_INTERVAL_SEC}"
      continue
    fi

    dish_local=$(echo "${dishes_local}" | jq -cr 'sort_by(.created_at) | last')
    if ! is_valid_json "${dish_local}"; then
      sleep "${TASK_TIMESTAMP_POLL_INTERVAL_SEC}"
      continue
    fi

    tasks_local=$(build_tasks_payload "${dish_local}")
    if ! is_valid_json "${tasks_local}"; then
      sleep "${TASK_TIMESTAMP_POLL_INTERVAL_SEC}"
      continue
    fi

    if [ "$(echo "${tasks_local}" | jq -r 'length')" -ge 2 ]; then
      started_count=$(echo "${tasks_local}" | jq -r '[.[] | select((.start_timestamp // .started_at) != null)] | length')
      if [ "${started_count}" -ge 2 ]; then
        echo "${tasks_local}"
        return 0
      fi
    fi

    now=$(date +%s)
    if [ "${now}" -ge "${deadline}" ]; then
      echo "${tasks_local}"
      return 0
    fi
    sleep "${TASK_TIMESTAMP_POLL_INTERVAL_SEC}"
  done
}

tasks=$(wait_for_task_starts)

if [ "$(echo "${tasks}" | jq -r 'length')" -lt 2 ]; then
  log_error "Expected at least two task entries from dish.result or dish ingredients"
  echo "${tasks}" | jq
  exit 1
fi

step_1=$(echo "${tasks}" | jq -cr 'map(select((.task_key // .task_id // "") | test("^step_1_"))) | sort_by(.start_timestamp // .started_at // .end_timestamp // .completed_at // "") | .[0]')
step_2=$(echo "${tasks}" | jq -cr 'map(select((.task_key // .task_id // "") | test("^step_2_"))) | sort_by(.start_timestamp // .started_at // .end_timestamp // .completed_at // "") | .[0]')

if [ -z "${step_1}" ] || [ "${step_1}" = "null" ] || [ -z "${step_2}" ] || [ "${step_2}" = "null" ]; then
  log_error "Could not find both step_1_* and step_2_* task entries in task payload"
  echo "${tasks}" | jq
  exit 1
fi

step_1_task_id=$(echo "${step_1}" | jq -r '.task_key // .task_id // empty')
step_1_start=$(echo "${step_1}" | jq -r '.start_timestamp // .started_at // empty')
step_1_end=$(echo "${step_1}" | jq -r '.end_timestamp // .completed_at // empty')
step_2_task_id=$(echo "${step_2}" | jq -r '.task_key // .task_id // empty')
step_2_start=$(echo "${step_2}" | jq -r '.start_timestamp // .started_at // empty')

if [ -z "${step_1_start}" ] || [ -z "${step_2_start}" ]; then
  log_error "Missing required start timestamps for step sequence assertion"
  echo "${tasks}" | jq
  exit 1
fi

step_1_start_norm=$(normalize_timestamp "${step_1_start}")
step_2_start_norm=$(normalize_timestamp "${step_2_start}")
step_1_start_epoch=$(to_epoch_seconds "${step_1_start_norm}")
step_2_start_epoch=$(to_epoch_seconds "${step_2_start_norm}")

log_info "Sequence check mode=${ASSERT_MODE}"
log_info "step_1=${step_1_task_id} start=${step_1_start_norm} end=${step_1_end:-<pending>}"
log_info "step_2=${step_2_task_id} start=${step_2_start_norm}"

if [ "${ASSERT_MODE}" = "blocking" ]; then
  if [ -z "${step_1_end}" ]; then
    log_error "Blocking assertion failed: step_1 has not completed yet"
    exit 1
  fi
  step_1_end_norm=$(normalize_timestamp "${step_1_end}")
  if [[ "${step_2_start_norm}" < "${step_1_end_norm}" ]]; then
    log_error "Blocking assertion failed: step_2 started before step_1 completed"
    exit 1
  fi
  log_info "Blocking assertion passed: step_2 starts at/after step_1 completion"
  exit 0
fi

if [ -n "${step_1_end}" ]; then
  step_1_end_norm=$(normalize_timestamp "${step_1_end}")
  if [[ "${step_2_start_norm}" < "${step_1_end_norm}" ]]; then
    log_info "Non-blocking assertion passed: step_2 overlaps with step_1"
    exit 0
  fi
fi

if [ $((step_2_start_epoch - step_1_start_epoch)) -le "${NON_BLOCKING_TOLERANCE_SEC}" ]; then
  log_info "Non-blocking assertion passed: step starts were near-simultaneous"
  exit 0
fi

log_error "Non-blocking assertion failed: step_2 did not start before step_1 completed"
exit 1

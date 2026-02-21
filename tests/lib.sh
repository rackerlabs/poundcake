#!/usr/bin/env bash
# Shared helpers for shell-based e2e tests.

: "${TEST_TARGET:=compose}"
: "${POUNDCAKE_NAMESPACE:=rackspace}"
: "${POUNDCAKE_API_SERVICE:=poundcake-api}"
: "${POUNDCAKE_LOCAL_PORT:=8000}"
: "${POUNDCAKE_REMOTE_PORT:=8000}"
: "${TEST_TIMEOUT_SEC:=30}"
: "${POLL_INTERVAL_SEC:=2}"
: "${DEBUG:=0}"
: "${TEST_TARGET_STARTED:=0}"

if [ -z "${API_URL:-}" ]; then
  if [ "${TEST_TARGET}" = "k8s" ]; then
    API_URL="http://localhost:${POUNDCAKE_LOCAL_PORT}/api/v1"
  else
    API_URL="http://localhost:8000/api/v1"
  fi
  if [ "${DEBUG}" = "1" ]; then
    echo "[DEBUG] API_URL defaulted by lib.sh to ${API_URL}" >&2
  fi
elif [ "${DEBUG}" = "1" ]; then
  echo "[DEBUG] API_URL inherited by lib.sh as ${API_URL}" >&2
fi

log_info() {
  echo "[INFO] $*"
}

log_warn() {
  echo "[WARN] $*" >&2
}

log_error() {
  echo "[ERROR] $*" >&2
}

debug_log() {
  if [ "${DEBUG}" = "1" ]; then
    echo "[DEBUG] $*" >&2
  fi
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log_error "${cmd} is required"
    exit 1
  fi
}

json_get() {
  local expr="$1"
  if ! jq -er "${expr}"; then
    log_error "jq query failed: ${expr}"
    exit 1
  fi
}

api_request_json() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local resp body code
  local curl_args=("-sS" "-X" "${method}" "${url}")

  if [ -n "${REQUEST_ID:-}" ]; then
    curl_args+=("-H" "X-Request-ID: ${REQUEST_ID}")
  fi

  if [ -n "${data}" ]; then
    curl_args+=("-H" "Content-Type: application/json" "-d" "${data}")
  else
    :
  fi

  resp=$(curl "${curl_args[@]}" -w $'\n%{http_code}')
  code="${resp##*$'\n'}"
  body="${resp%$'\n'*}"
  debug_log "${method} ${url} -> HTTP ${code}"

  if [ "${code}" -lt 200 ] || [ "${code}" -ge 300 ]; then
    log_error "API request failed: ${method} ${url} (HTTP ${code})"
    echo "${body}" >&2
    exit 1
  fi

  if ! echo "${body}" | jq -e . >/dev/null 2>&1; then
    log_error "API response is not valid JSON: ${method} ${url}"
    echo "${body}" >&2
    exit 1
  fi

  echo "${body}"
}

run_step() {
  local label="$1"
  shift
  log_info "START ${label}"
  if "$@"; then
    log_info "OK ${label}"
  else
    local rc=$?
    log_error "FAIL ${label} (exit ${rc})"
    return "${rc}"
  fi
}

append_no_proxy_localhost() {
  local current="${1:-}"
  local needed=("localhost" "127.0.0.1" "::1")
  local out="${current}"
  local item
  for item in "${needed[@]}"; do
    if [[ ",${out}," != *",${item},"* ]]; then
      if [ -n "${out}" ]; then
        out="${out},${item}"
      else
        out="${item}"
      fi
    fi
  done
  echo "${out}"
}

wait_for_api_ready() {
  local timeout="${1:-20}"
  local start now
  start=$(date +%s)
  while true; do
    if curl -sS -o /dev/null -m 2 "${API_URL}/health"; then
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "${timeout}" ]; then
      return 1
    fi
    sleep 1
  done
}

start_k8s_port_forward() {
  require_cmd kubectl

  if lsof -iTCP:"${POUNDCAKE_LOCAL_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    log_error "Local port ${POUNDCAKE_LOCAL_PORT} is already in use"
    log_error "Set POUNDCAKE_LOCAL_PORT to an unused port and retry"
    exit 1
  fi

  export NO_PROXY
  export no_proxy
  NO_PROXY="$(append_no_proxy_localhost "${NO_PROXY:-}")"
  no_proxy="$(append_no_proxy_localhost "${no_proxy:-}")"
  debug_log "NO_PROXY=${NO_PROXY}"
  debug_log "no_proxy=${no_proxy}"

  log_info "Starting kubectl port-forward ${POUNDCAKE_NAMESPACE}/svc/${POUNDCAKE_API_SERVICE} ${POUNDCAKE_LOCAL_PORT}:${POUNDCAKE_REMOTE_PORT}"
  kubectl -n "${POUNDCAKE_NAMESPACE}" port-forward "svc/${POUNDCAKE_API_SERVICE}" "${POUNDCAKE_LOCAL_PORT}:${POUNDCAKE_REMOTE_PORT}" >/tmp/poundcake-test-portforward.log 2>&1 &
  TEST_PORT_FORWARD_PID=$!
  export TEST_PORT_FORWARD_PID

  if ! wait_for_api_ready 25; then
    log_error "Timed out waiting for API readiness via port-forward at ${API_URL}"
    log_error "kubectl port-forward output:"
    tail -n 50 /tmp/poundcake-test-portforward.log >&2 || true
    stop_test_target
    exit 1
  fi
  log_info "Port-forward established and API reachable at ${API_URL}"
}

start_test_target() {
  if [ "${TEST_TARGET_STARTED}" = "1" ]; then
    debug_log "Test target already started; skipping start"
    return 0
  fi

  case "${TEST_TARGET}" in
    compose)
      log_info "Using compose target with API_URL=${API_URL}"
      ;;
    k8s)
      start_k8s_port_forward
      ;;
    *)
      log_error "Invalid TEST_TARGET='${TEST_TARGET}' (expected compose or k8s)"
      exit 1
      ;;
  esac

  TEST_TARGET_STARTED=1
  export TEST_TARGET_STARTED
}

stop_test_target() {
  if [ -n "${TEST_PORT_FORWARD_PID:-}" ] && kill -0 "${TEST_PORT_FORWARD_PID}" >/dev/null 2>&1; then
    log_info "Stopping kubectl port-forward (pid=${TEST_PORT_FORWARD_PID})"
    kill "${TEST_PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    wait "${TEST_PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
}

register_cleanup_trap() {
  if [ "${TEST_CLEANUP_TRAP_SET:-0}" = "1" ]; then
    return 0
  fi
  trap 'stop_test_target' EXIT INT TERM
  TEST_CLEANUP_TRAP_SET=1
  export TEST_CLEANUP_TRAP_SET
}

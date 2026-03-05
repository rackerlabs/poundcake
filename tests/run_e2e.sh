#!/usr/bin/env bash
# Unified entrypoint for shell-based e2e workflow tests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

RUN_ALL_SCRIPT="${SCRIPT_DIR}/run_all_e2e_workflow_generation_tests"
api_url_explicit="false"
service_explicit="false"
namespace_explicit="false"
local_port_explicit="false"
enable_port_forward="false"

print_usage() {
  cat <<'EOF'
Usage:
  ./tests/run_e2e.sh [options]

Runs shell-based e2e workflow tests.
By default, runs the full e2e workflow suite.

Options:
  --target <compose|k8s>     Execution target (default: compose)
  --namespace <name>         Kubernetes namespace (k8s mode)
  --service <name>           Kubernetes API service name (k8s mode)
  --enable-port-forward      Enable kubectl port-forward in k8s mode
  --local-port <port>        Local port for k8s port-forward (requires --enable-port-forward)
  --remote-port <port>       Remote service port for k8s service URL / port-forward
  --api-url <url>            Explicit API base URL override
  --single <runner>          Run one runner script (name or path)
  --list                     List available runner scripts
  -h, --help                 Show this help

Examples:
  ./tests/run_e2e.sh
  ./tests/run_e2e.sh --target k8s --namespace rackspace --service poundcake-api
  ./tests/run_e2e.sh --target k8s --namespace rackspace --service poundcake-api --enable-port-forward --local-port 18000
  ./tests/run_e2e.sh --single run_single_task_non_blocking_test
EOF
}

list_runners() {
  cat <<'EOF'
run_single_task_non_blocking_test
run_single_task_manual_order_test
run_single_task_webhook_counter_increment_test
run_multiple_tasks_non_blocking_test
run_multiple_tasks_with_blocking_test
run_host_down_expected_failure_test
run_reuse_recipe_two_webhooks_test
run_fallback_unmatched_alert_bakery_observation_test
EOF
}

resolve_runner_path() {
  local runner="$1"
  local path_candidate

  if [[ "${runner}" = /* ]]; then
    path_candidate="${runner}"
  elif [[ "${runner}" == */* ]]; then
    path_candidate="${SCRIPT_DIR}/${runner}"
  else
    path_candidate="${SCRIPT_DIR}/${runner}"
  fi

  if [ ! -f "${path_candidate}" ]; then
    log_error "Runner script not found: ${runner}"
    return 1
  fi

  echo "${path_candidate}"
}

require_value() {
  local flag="$1"
  local value="${2:-}"
  if [ -z "${value}" ] || [[ "${value}" == --* ]]; then
    log_error "Missing value for ${flag}"
    exit 1
  fi
}

resolve_api_url() {
  if [ "${api_url_explicit}" = "true" ]; then
    echo "${API_URL}"
    return
  fi

  if [ "${TEST_TARGET}" = "k8s" ]; then
    echo "http://${POUNDCAKE_API_SERVICE}.${POUNDCAKE_NAMESPACE}.svc.cluster.local:${POUNDCAKE_REMOTE_PORT}/api/v1"
    return
  fi

  echo "http://localhost:8000/api/v1"
}

single_runner=""
list_only="false"

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      require_value "$1" "${2:-}"
      TEST_TARGET="${2:-}"
      shift 2
      ;;
    --namespace)
      require_value "$1" "${2:-}"
      POUNDCAKE_NAMESPACE="${2:-}"
      namespace_explicit="true"
      shift 2
      ;;
    --service)
      require_value "$1" "${2:-}"
      POUNDCAKE_API_SERVICE="${2:-}"
      service_explicit="true"
      shift 2
      ;;
    --local-port)
      require_value "$1" "${2:-}"
      POUNDCAKE_LOCAL_PORT="${2:-}"
      local_port_explicit="true"
      shift 2
      ;;
    --remote-port)
      require_value "$1" "${2:-}"
      POUNDCAKE_REMOTE_PORT="${2:-}"
      shift 2
      ;;
    --enable-port-forward)
      enable_port_forward="true"
      shift
      ;;
    --api-url)
      require_value "$1" "${2:-}"
      API_URL="${2:-}"
      api_url_explicit="true"
      shift 2
      ;;
    --single)
      require_value "$1" "${2:-}"
      single_runner="${2:-}"
      shift 2
      ;;
    --list)
      list_only="true"
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      if [ "$1" = "--api-rul" ]; then
        log_error "Unknown argument --api-rul; did you mean --api-url?"
      else
        log_error "Unknown argument: $1"
      fi
      print_usage
      exit 1
      ;;
  esac
done

if [ -z "${TEST_TARGET:-}" ]; then
  TEST_TARGET="compose"
fi

if [ "${TEST_TARGET}" != "compose" ] && [ "${TEST_TARGET}" != "k8s" ]; then
  log_error "Invalid --target value: ${TEST_TARGET} (expected compose or k8s)"
  exit 1
fi

if [ "${api_url_explicit}" = "true" ] && [ -z "${API_URL}" ]; then
  log_error "--api-url requires a non-empty value"
  exit 1
fi

if [ "${service_explicit}" = "true" ] && [ -z "${POUNDCAKE_API_SERVICE}" ]; then
  log_error "--service requires a non-empty value"
  exit 1
fi

if [ "${TEST_TARGET}" = "compose" ] && [ "${service_explicit}" = "true" ]; then
  log_error "--service is only valid with --target k8s"
  exit 1
fi

if [ "${TEST_TARGET}" = "compose" ] && [ "${enable_port_forward}" = "true" ]; then
  log_error "--enable-port-forward is only valid with --target k8s"
  exit 1
fi

if [ "${local_port_explicit}" = "true" ] && [ "${enable_port_forward}" != "true" ]; then
  log_error "--local-port requires --enable-port-forward"
  exit 1
fi

if [ "${TEST_TARGET}" = "k8s" ] && [ "${api_url_explicit}" != "true" ] && [ "${service_explicit}" != "true" ]; then
  log_error "--target k8s requires --service unless --api-url is provided"
  exit 1
fi

if [ -z "${POUNDCAKE_NAMESPACE}" ]; then
  if [ "${namespace_explicit}" = "true" ]; then
    log_error "--namespace requires a non-empty value"
  else
    log_error "POUNDCAKE_NAMESPACE must not be empty"
  fi
  exit 1
fi

if [ -z "${POUNDCAKE_REMOTE_PORT}" ] || ! [[ "${POUNDCAKE_REMOTE_PORT}" =~ ^[0-9]+$ ]]; then
  log_error "--remote-port must be a non-empty numeric value"
  exit 1
fi

# lib.sh is sourced before CLI parsing; compute the final API_URL after parsing.
API_URL="$(resolve_api_url)"

log_info "Resolved poundcake_api URL: ${API_URL}"

# Child runner processes source lib.sh again; export runtime settings so they inherit CLI args.
export TEST_TARGET
export POUNDCAKE_NAMESPACE
export POUNDCAKE_API_SERVICE
export POUNDCAKE_LOCAL_PORT
export POUNDCAKE_REMOTE_PORT
if [ "${enable_port_forward}" = "true" ]; then
  ENABLE_PORT_FORWARD="1"
else
  ENABLE_PORT_FORWARD="0"
fi
export ENABLE_PORT_FORWARD
export API_URL

if [ "${list_only}" = "true" ]; then
  list_runners
  exit 0
fi

if [ -n "${single_runner}" ]; then
  runner_script="$(resolve_runner_path "${single_runner}")"
  log_info "Running single e2e runner: $(basename "${runner_script}")"
  start_test_target
  register_cleanup_trap
  "${runner_script}"
  exit 0
fi

log_info "Running full e2e workflow-generation suite"
"${RUN_ALL_SCRIPT}"

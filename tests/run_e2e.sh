#!/usr/bin/env bash
# Unified entrypoint for shell-based e2e workflow tests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

RUN_ALL_SCRIPT="${SCRIPT_DIR}/run_all_e2e_workflow_generation_tests"

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
  --local-port <port>        Local port for k8s port-forward
  --remote-port <port>       Remote service port for k8s port-forward
  --api-url <url>            Explicit API base URL override
  --single <runner>          Run one runner script (name or path)
  --list                     List available runner scripts
  -h, --help                 Show this help

Examples:
  ./tests/run_e2e.sh
  ./tests/run_e2e.sh --target k8s --namespace rackspace --service poundcake-api --local-port 18000
  ./tests/run_e2e.sh --single run_single_task_non_blocking_test
EOF
}

list_runners() {
  cat <<'EOF'
run_single_task_non_blocking_test
run_single_task_manual_order_test
run_multiple_tasks_non_blocking_test
run_multiple_tasks_with_blocking_test
run_reuse_recipe_two_webhooks_test
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

single_runner=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      TEST_TARGET="${2:-}"
      shift 2
      ;;
    --namespace)
      POUNDCAKE_NAMESPACE="${2:-}"
      shift 2
      ;;
    --service)
      POUNDCAKE_API_SERVICE="${2:-}"
      shift 2
      ;;
    --local-port)
      POUNDCAKE_LOCAL_PORT="${2:-}"
      shift 2
      ;;
    --remote-port)
      POUNDCAKE_REMOTE_PORT="${2:-}"
      shift 2
      ;;
    --api-url)
      API_URL="${2:-}"
      shift 2
      ;;
    --single)
      single_runner="${2:-}"
      shift 2
      ;;
    --list)
      list_runners
      exit 0
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      log_error "Unknown argument: $1"
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

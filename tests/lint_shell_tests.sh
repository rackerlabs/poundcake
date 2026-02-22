#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash -n "${SCRIPT_DIR}"/*.sh "${SCRIPT_DIR}"/run_* "${SCRIPT_DIR}"/run_all_e2e_workflow_generation_tests

RUNNERS=(
  "${SCRIPT_DIR}/run_single_task_non_blocking_test"
  "${SCRIPT_DIR}/run_single_task_manual_order_test"
  "${SCRIPT_DIR}/run_single_task_webhook_counter_increment_test"
  "${SCRIPT_DIR}/run_multiple_tasks_non_blocking_test"
  "${SCRIPT_DIR}/run_multiple_tasks_with_blocking_test"
  "${SCRIPT_DIR}/run_reuse_recipe_two_webhooks_test"
  "${SCRIPT_DIR}/run_all_e2e_workflow_generation_tests"
)

for runner in "${RUNNERS[@]}"; do
  grep -q 'source "${SCRIPT_DIR}/lib.sh"' "${runner}"
  grep -q 'start_test_target' "${runner}"
  grep -q 'register_cleanup_trap' "${runner}"
done

echo "Shell syntax checks passed."

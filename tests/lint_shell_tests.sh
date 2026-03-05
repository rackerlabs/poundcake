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
  "${SCRIPT_DIR}/run_host_down_expected_failure_test"
  "${SCRIPT_DIR}/run_reuse_recipe_two_webhooks_test"
  "${SCRIPT_DIR}/run_fallback_unmatched_alert_bakery_observation_test"
  "${SCRIPT_DIR}/run_all_e2e_workflow_generation_tests"
)

for runner in "${RUNNERS[@]}"; do
  grep -q 'source "${SCRIPT_DIR}/lib.sh"' "${runner}"
  grep -q 'start_test_target' "${runner}"
  grep -q 'register_cleanup_trap' "${runner}"
done

legacy_keys_pattern='\b(workflow_payload|workflow_parameters|input_parameters|action_parameters|source_type)\b'
if grep -R -nE "${legacy_keys_pattern}" \
  "${SCRIPT_DIR}" \
  --include='*.sh' \
  --include='run_*' \
  --exclude='lint_shell_tests.sh'; then
  echo "Legacy recipe/ingredient payload keys found in shell tests." >&2
  exit 1
fi

echo "Shell syntax checks passed."

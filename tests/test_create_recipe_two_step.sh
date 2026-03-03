#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Create a two-step recipe with ingredients and tasks, without creating an order
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

TEST_RECIPE=${TEST_RECIPE:-}
IS_BLOCKING=${IS_BLOCKING:-false}
STEP1_CMD=${STEP1_CMD:-'echo "step 1"'}
STEP2_CMD=${STEP2_CMD:-'echo "step 2"'}
ING_ON_FAILURE=${ING_ON_FAILURE:-stop}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

require_cmd curl
require_cmd jq

log_info "Creating two-step recipe: ${TEST_RECIPE} (is_blocking=${IS_BLOCKING})"

# Use a unique task key when we need to create the core.local ingredient.
INGREDIENT_SUFFIX=$(printf "%s" "${TEST_RECIPE}-$$-${RANDOM}" \
  | tr '[:upper:]' '[:lower:]' \
  | tr -cs 'a-z0-9' '_' \
  | sed -e 's/^_//' -e 's/_$//' \
  | cut -c1-48)
ING_EXECUTION_TARGET="core.local"
ING_TASK_KEY_TEMPLATE="echo_${INGREDIENT_SUFFIX}"

ING1_ID=$(api_request_json GET "${API_URL}/ingredients/?execution_target=${ING_EXECUTION_TARGET}" | jq -r '.[0].id // empty')

if [ -z "$ING1_ID" ] || [ "$ING1_ID" = "null" ]; then
  log_info "Ingredient ${ING_EXECUTION_TARGET} not found, creating it..."
  ING1_PAYLOAD=$(jq -n \
    --arg execution_engine "stackstorm" \
    --arg execution_target "${ING_EXECUTION_TARGET}" \
    --arg task_key_template "${ING_TASK_KEY_TEMPLATE}" \
    --argjson is_blocking "$IS_BLOCKING" \
    --arg on_failure "$ING_ON_FAILURE" \
    '{
      execution_engine: $execution_engine,
      execution_target: $execution_target,
      task_key_template: $task_key_template,
      execution_parameters: {
        cmd: {
          type: "string",
          description: "Command to execute",
          required: true
        }
      },
      is_blocking: $is_blocking,
      expected_duration_sec: 30,
      timeout_duration_sec: 300,
      retry_count: 0,
      retry_delay: 5,
      on_failure: $on_failure
    }')

  ING1_ID=$(api_request_json POST "${API_URL}/ingredients/" "${ING1_PAYLOAD}" | jq -r '.id')

  if [ -z "$ING1_ID" ] || [ "$ING1_ID" = "null" ]; then
    log_error "Failed to create ingredient ${ING_EXECUTION_TARGET}"
    exit 1
  fi
else
  log_info "Using existing ingredient ${ING_EXECUTION_TARGET} (ID: $ING1_ID)"
fi

# Reuse the same unique ingredient for both recipe steps.
ING2_ID="$ING1_ID"

if [ "${IS_BLOCKING}" = "true" ]; then
  STEP1_DEPTH=0
  STEP2_DEPTH=1
else
  STEP1_DEPTH=0
  STEP2_DEPTH=0
fi

RECIPE_PAYLOAD=$(jq -n \
  --arg name "$TEST_RECIPE" \
  --arg desc "Automated two-step test recipe" \
  --arg step1_cmd "$STEP1_CMD" \
  --arg step2_cmd "$STEP2_CMD" \
  --argjson ing1_id "$ING1_ID" \
  --argjson ing2_id "$ING2_ID" \
  --argjson step1_depth "$STEP1_DEPTH" \
  --argjson step2_depth "$STEP2_DEPTH" \
  '{
    name: $name,
    description: $desc,
    enabled: true,
    recipe_ingredients: [
      {
        ingredient_id: $ing1_id,
        step_order: 1,
        on_success: "continue",
        parallel_group: 0,
        depth: $step1_depth,
        execution_parameters_override: {
          cmd: $step1_cmd
        }
      },
      {
        ingredient_id: $ing2_id,
        step_order: 2,
        on_success: "continue",
        parallel_group: 0,
        depth: $step2_depth,
        execution_parameters_override: {
          cmd: $step2_cmd
        }
      }
    ]
  }')

api_request_json POST "${API_URL}/recipes/" "${RECIPE_PAYLOAD}" | jq -r '.id'

#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Create a single-step recipe with ingredient and task, without creating an order
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

TEST_RECIPE=${TEST_RECIPE:-}
IS_BLOCKING=${IS_BLOCKING:-false}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

require_cmd curl
require_cmd jq

log_info "Creating single-step recipe: ${TEST_RECIPE} (is_blocking=${IS_BLOCKING})"

ING_TASK_KEY_TEMPLATE="single_echo"

# Check if the expected core.local ingredient already exists.
ING_ID=$(
  api_request_json GET \
    "${API_URL}/ingredients/?execution_target=core.local&task_key_template=${ING_TASK_KEY_TEMPLATE}" \
    | jq -r '.[0].id // empty'
)

if [ -z "$ING_ID" ] || [ "$ING_ID" = "null" ]; then
  log_info "Ingredient core.local not found, creating it..."
  ING_PAYLOAD=$(jq -n \
    --arg execution_engine "stackstorm" \
    --arg task_key_template "${ING_TASK_KEY_TEMPLATE}" \
    --argjson is_blocking "$IS_BLOCKING" \
    '{
      execution_engine: $execution_engine,
      execution_target: "core.local",
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
      on_failure: "stop"
    }')

  ING_ID=$(api_request_json POST "${API_URL}/ingredients/" "${ING_PAYLOAD}" | jq -r '.id')

  if [ -z "$ING_ID" ] || [ "$ING_ID" = "null" ]; then
    log_error "Failed to create ingredient"
    exit 1
  fi
else
  log_info "Using existing ingredient core.local/${ING_TASK_KEY_TEMPLATE} (ID: $ING_ID)"
fi

RECIPE_PAYLOAD=$(jq -n \
  --arg name "$TEST_RECIPE" \
  --arg desc "Automated single-step test recipe" \
  --argjson ing_id "$ING_ID" \
  '{
    name: $name,
    description: $desc,
    enabled: true,
    recipe_ingredients: [
      {
        ingredient_id: $ing_id,
        step_order: 1,
        on_success: "continue",
        parallel_group: 0,
        depth: 0,
        execution_parameters_override: {
          cmd: "echo \"single step test\""
        }
      }
    ]
  }')

api_request_json POST "${API_URL}/recipes/" "${RECIPE_PAYLOAD}" | jq -r '.id'

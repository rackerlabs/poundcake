#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Create a single-step recipe with ingredient and task, without creating an order
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000/api/v1}
TEST_RECIPE=${TEST_RECIPE:-}
IS_BLOCKING=${IS_BLOCKING:-false}

if [ -z "$TEST_RECIPE" ]; then
  echo "TEST_RECIPE is required"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

echo "Creating single-step recipe: ${TEST_RECIPE} (is_blocking=${IS_BLOCKING})"

ING_PAYLOAD=$(jq -n \
  --arg cmd "echo \"alert single task\"" \
  --argjson is_blocking "$IS_BLOCKING" \
  '{
    task_id: "core.local",
    task_name: "single_echo",
    action_parameters: {cmd: $cmd},
    is_blocking: $is_blocking,
    expected_duration_sec: 30,
    timeout_duration_sec: 300,
    retry_count: 0,
    retry_delay: 5,
    on_failure: "stop"
  }')

ING_ID=$(curl -sS -X POST "${API_URL}/ingredients/" \
  -H "Content-Type: application/json" \
  -d "${ING_PAYLOAD}" | jq -r '.id')

if [ -z "$ING_ID" ]; then
  echo "Failed to create ingredient"
  exit 1
fi

RECIPE_PAYLOAD=$(jq -n \
  --arg name "$TEST_RECIPE" \
  --arg desc "Automated single-step test recipe" \
  --arg cmd "echo \"alert single task\"" \
  --argjson ing_id "$ING_ID" \
  '{
    name: $name,
    description: $desc,
    enabled: true,
    workflow_payload: {
      version: "1.0",
      description: "Single-step test workflow",
      tasks: {
        single_echo: {
          action: "core.local",
          input: {cmd: $cmd}
        }
      }
    },
    workflow_parameters: {},
    recipe_ingredients: [
      {ingredient_id: $ing_id, step_order: 1, on_success: "continue", parallel_group: 0, depth: 0}
    ]
  }')

curl -sS -X POST "${API_URL}/recipes/" \
  -H "Content-Type: application/json" \
  -d "${RECIPE_PAYLOAD}" | jq -r '.id'

#!/usr/bin/env bash
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

echo "Creating two-step recipe: ${TEST_RECIPE} (is_blocking=${IS_BLOCKING})"

ING1_PAYLOAD=$(jq -n \
  --arg cmd "echo \"alert step one task\"" \
  --argjson is_blocking "$IS_BLOCKING" \
  '{
    task_id: "core.local",
    task_name: "step_1_echo",
    action_parameters: {cmd: $cmd},
    is_blocking: $is_blocking,
    expected_duration_sec: 30,
    timeout_duration_sec: 300,
    retry_count: 0,
    retry_delay: 5,
    on_failure: "stop"
  }')

ING2_PAYLOAD=$(jq -n \
  --arg cmd "echo \"alert step two task\"" \
  --argjson is_blocking "$IS_BLOCKING" \
  '{
    task_id: "core.local",
    task_name: "step_2_echo",
    action_parameters: {cmd: $cmd},
    is_blocking: $is_blocking,
    expected_duration_sec: 30,
    timeout_duration_sec: 300,
    retry_count: 0,
    retry_delay: 5,
    on_failure: "stop"
  }')

ING1_ID=$(curl -sS -X POST "${API_URL}/ingredients/" \
  -H "Content-Type: application/json" \
  -d "${ING1_PAYLOAD}" | jq -r '.id')

ING2_ID=$(curl -sS -X POST "${API_URL}/ingredients/" \
  -H "Content-Type: application/json" \
  -d "${ING2_PAYLOAD}" | jq -r '.id')

if [ -z "$ING1_ID" ] || [ -z "$ING2_ID" ]; then
  echo "Failed to create ingredients"
  exit 1
fi

RECIPE_PAYLOAD=$(jq -n \
  --arg name "$TEST_RECIPE" \
  --arg desc "Automated two-step test recipe" \
  --arg cmd1 "echo \"alert step one task\"" \
  --arg cmd2 "echo \"alert step two task\"" \
  --argjson ing1_id "$ING1_ID" \
  --argjson ing2_id "$ING2_ID" \
  '{
    name: $name,
    description: $desc,
    enabled: true,
    workflow_payload: {
      version: "1.0",
      description: "Two-step test workflow",
      tasks: {
        step_1_echo: {
          action: "core.local",
          input: {cmd: $cmd1},
          next: [{when: "<% succeeded() %>", do: "step_2_echo"}]
        },
        step_2_echo: {
          action: "core.local",
          input: {cmd: $cmd2}
        }
      }
    },
    workflow_parameters: {},
    recipe_ingredients: [
      {ingredient_id: $ing1_id, step_order: 1, on_success: "continue", parallel_group: 0, depth: 0},
      {ingredient_id: $ing2_id, step_order: 2, on_success: "continue", parallel_group: 1, depth: 1}
    ]
  }')

curl -sS -X POST "${API_URL}/recipes/" \
  -H "Content-Type: application/json" \
  -d "${RECIPE_PAYLOAD}" | jq -r '.id'

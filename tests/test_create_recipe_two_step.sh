#!/usr/bin/env bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# Test: Create a two-step recipe with ingredients and tasks, without creating an order
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

# Check if core.local ingredient already exists
ING1_ID=$(curl -sS -X GET "${API_URL}/ingredients/?task_id=core.local" | jq -r '.[0].id // empty')

if [ -z "$ING1_ID" ] || [ "$ING1_ID" = "null" ]; then
  echo "Ingredient core.local not found, creating it..."
  ING1_PAYLOAD=$(jq -n \
    --argjson is_blocking "$IS_BLOCKING" \
    '{
      task_id: "core.local",
      task_name: "step_1_echo",
      action_parameters: {
        cmd: {
          type: "string",
          description: "Command to execute",
          required: true
        }
      },
      source_type: "stackstorm",
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

  if [ -z "$ING1_ID" ] || [ "$ING1_ID" = "null" ]; then
    echo "Failed to create first ingredient"
    exit 1
  fi
else
  echo "Using existing ingredient core.local (ID: $ING1_ID)"
fi

# For the second step, we'll use the same ingredient (core.local can be reused in different steps)
ING2_ID="$ING1_ID"

RECIPE_PAYLOAD=$(jq -n \
  --arg name "$TEST_RECIPE" \
  --arg desc "Automated two-step test recipe" \
  --argjson ing1_id "$ING1_ID" \
  --argjson ing2_id "$ING2_ID" \
  '{
    name: $name,
    description: $desc,
    enabled: true,
    workflow_payload: null,
    workflow_parameters: {},
    recipe_ingredients: [
      {
        ingredient_id: $ing1_id,
        step_order: 1,
        on_success: "continue",
        parallel_group: 0,
        depth: 0,
        input_parameters: {
          cmd: "echo \"step 1\""
        }
      },
      {
        ingredient_id: $ing2_id,
        step_order: 2,
        on_success: "continue",
        parallel_group: 0,
        depth: 0,
        input_parameters: {
          cmd: "echo \"step 2\""
        }
      }
    ]
  }')

curl -sS -X POST "${API_URL}/recipes/" \
  -H "Content-Type: application/json" \
  -d "${RECIPE_PAYLOAD}" | jq -r '.id'

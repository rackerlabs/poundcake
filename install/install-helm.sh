#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ -n "${POUNDCAKE_STACKSTORM_CHART_ENABLED:-}" ]]; then
  echo "Note: POUNDCAKE_STACKSTORM_CHART_ENABLED is deprecated and ignored. Installer now manages StackStorm as a separate chart."
fi

exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "$@"

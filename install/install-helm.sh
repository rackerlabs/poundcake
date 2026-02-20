#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  exec "$PROJECT_ROOT/helm/bin/install-poundcake-with-env.sh" "$@"
fi

exec "$PROJECT_ROOT/helm/bin/install-poundcake-with-env.sh" "$@"

#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

for arg in "$@"; do
  case "${arg}" in
    --target|--target=*)
      echo "install-poundcake-helm.sh no longer supports --target." >&2
      echo "Use install/install-poundcake-helm.sh for PoundCake or install/install-bakery-helm.sh for Bakery." >&2
      exit 1
      ;;
  esac
done

exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "$@"

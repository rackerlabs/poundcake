#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

TARGET="${POUNDCAKE_INSTALL_TARGET:-poundcake}"
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

case "${TARGET}" in
  poundcake)
    exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "${ARGS[@]}"
    ;;
  bakery)
    exec "$PROJECT_ROOT/helm/bin/install-bakery.sh" "${ARGS[@]}"
    ;;
  both)
    exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" --enable-bakery "${ARGS[@]}"
    ;;
  *)
    cat >&2 <<EOF
Invalid target '${TARGET}'. Valid values: poundcake, bakery, both.
Usage: ./install/install-poundcake-helm.sh [--target <poundcake|bakery|both>] [installer options] [helm args]
EOF
    exit 1
    ;;
esac

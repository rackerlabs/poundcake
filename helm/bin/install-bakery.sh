#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POUNDCAKE_INSTALLER="${SCRIPT_DIR}/install-poundcake.sh"

if [[ ! -x "${POUNDCAKE_INSTALLER}" ]]; then
  echo "[ERROR] Missing installer: ${POUNDCAKE_INSTALLER}" >&2
  exit 1
fi

reject_integrated_flags() {
  local arg=""
  for arg in "$@"; do
    case "${arg}" in
      --mode|--mode=*|--no-local-bakery|--bakery-db-integrated|--bakery-db-host|--bakery-db-host=*|--bakery-db-name|--bakery-db-name=*|--bakery-db-user|--bakery-db-user=*)
        echo "[ERROR] Option '${arg}' is not supported by install-bakery.sh." >&2
        echo "[ERROR] Bakery installer enforces standalone DB server provisioning." >&2
        exit 1
        ;;
      --set=*|--set-string=*|--set-json=*|--set-literal=*|--set-file=*)
        if [[ "${arg}" == *"bakery.database.createServer=false"* ]]; then
          echo "[ERROR] bakery.database.createServer=false is not supported by install-bakery.sh." >&2
          exit 1
        fi
        ;;
    esac
  done

  local argv=("$@")
  local i=0
  local token=""
  local next=""
  while [[ ${i} -lt ${#argv[@]} ]]; do
    token="${argv[$i]}"
    next="${argv[$((i + 1))]:-}"
    if [[ "${token}" == "--set" || "${token}" == "--set-string" || "${token}" == "--set-json" || "${token}" == "--set-literal" || "${token}" == "--set-file" ]]; then
      if [[ "${next}" == *"bakery.database.createServer=false"* ]]; then
        echo "[ERROR] bakery.database.createServer=false is not supported by install-bakery.sh." >&2
        exit 1
      fi
      i=$((i + 2))
      continue
    fi
    i=$((i + 1))
  done
}

if [[ "${POUNDCAKE_BAKERY_DB_INTEGRATED:-false}" == "true" ]]; then
  echo "[ERROR] POUNDCAKE_BAKERY_DB_INTEGRATED=true is not supported by install-bakery.sh." >&2
  exit 1
fi

if [[ "${POUNDCAKE_NO_LOCAL_BAKERY:-false}" == "true" ]]; then
  echo "[ERROR] POUNDCAKE_NO_LOCAL_BAKERY=true is not supported by install-bakery.sh." >&2
  exit 1
fi

reject_integrated_flags "$@"

exec env POUNDCAKE_ENABLED=false "${POUNDCAKE_INSTALLER}" \
  --set-string poundcake.enabled=false \
  --set-string bakery.enabled=true \
  --set-string bakery.database.createServer=true \
  "$@"

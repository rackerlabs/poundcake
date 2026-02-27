#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POUNDCAKE_INSTALLER="${SCRIPT_DIR}/install-poundcake.sh"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
BAKERY_RACKSPACE_SECRET_NAME="${POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME:-bakery-rackspace-core}"
BAKERY_RACKSPACE_URL="${POUNDCAKE_BAKERY_RACKSPACE_URL:-}"
BAKERY_RACKSPACE_USERNAME="${POUNDCAKE_BAKERY_RACKSPACE_USERNAME:-}"
BAKERY_RACKSPACE_PASSWORD="${POUNDCAKE_BAKERY_RACKSPACE_PASSWORD:-}"
UPDATE_BAKERY_SECRET="${POUNDCAKE_UPDATE_BAKERY_SECRET:-false}"
FORWARD_ARGS=()

if [[ ! -x "${POUNDCAKE_INSTALLER}" ]]; then
  echo "[ERROR] Missing installer: ${POUNDCAKE_INSTALLER}" >&2
  exit 1
fi

log_info() {
  echo "[INFO] $*" >&2
}

log_error() {
  echo "[ERROR] $*" >&2
}

normalize_bool() {
  local value="${1:-}"
  value="$(echo "${value}" | tr '[:upper:]' '[:lower:]')"
  case "${value}" in
    true|false)
      echo "${value}"
      ;;
    *)
      echo ""
      ;;
  esac
}

usage() {
  cat <<'USAGE_EOF'
Usage:
  install-bakery.sh [bakery secret options] [installer/helm args]

Bakery secret options:
  --bakery-rackspace-secret-name <name>   Secret name to verify/create (default: bakery-rackspace-core)
  --bakery-rackspace-url <url>            Rackspace Core URL for secret creation/update
  --bakery-rackspace-username <username>  Rackspace Core username for secret creation/update
  --bakery-rackspace-password <password>  Rackspace Core password for secret creation/update
  --update-bakery-secret                  Update existing secret (prompts for missing values)

Behavior:
  - If the secret exists, installer uses it and does not prompt.
  - If the secret is missing, installer creates it (prompts for missing values).
  - Existing secret is only updated when --update-bakery-secret is provided.

All remaining args are forwarded to install-poundcake.sh.
USAGE_EOF
}

prompt_for_missing_bakery_credentials() {
  if [[ -z "${BAKERY_RACKSPACE_URL}" ]]; then
    read -r -p "Rackspace Core URL: " BAKERY_RACKSPACE_URL
  fi
  while [[ -z "${BAKERY_RACKSPACE_URL}" ]]; do
    read -r -p "Rackspace Core URL (required): " BAKERY_RACKSPACE_URL
  done

  if [[ -z "${BAKERY_RACKSPACE_USERNAME}" ]]; then
    read -r -p "Rackspace Core Username: " BAKERY_RACKSPACE_USERNAME
  fi
  while [[ -z "${BAKERY_RACKSPACE_USERNAME}" ]]; do
    read -r -p "Rackspace Core Username (required): " BAKERY_RACKSPACE_USERNAME
  done

  if [[ -z "${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    read -r -s -p "Rackspace Core Password: " BAKERY_RACKSPACE_PASSWORD
    echo
  fi
  while [[ -z "${BAKERY_RACKSPACE_PASSWORD}" ]]; do
    read -r -s -p "Rackspace Core Password (required): " BAKERY_RACKSPACE_PASSWORD
    echo
  done
}

ensure_bakery_secret() {
  local secret_exists="false"
  local needs_create_or_update="false"
  local provided_creds="false"

  if [[ -n "${BAKERY_RACKSPACE_URL}" || -n "${BAKERY_RACKSPACE_USERNAME}" || -n "${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    provided_creds="true"
  fi

  if kubectl -n "${NAMESPACE}" get secret "${BAKERY_RACKSPACE_SECRET_NAME}" >/dev/null 2>&1; then
    secret_exists="true"
  fi

  if [[ "${secret_exists}" == "false" || "${UPDATE_BAKERY_SECRET}" == "true" ]]; then
    needs_create_or_update="true"
  fi

  if [[ "${secret_exists}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" && "${provided_creds}" == "true" ]]; then
    log_error "Bakery secret '${BAKERY_RACKSPACE_SECRET_NAME}' already exists in namespace '${NAMESPACE}'."
    log_error "Use --update-bakery-secret to update it."
    exit 1
  fi

  if [[ "${needs_create_or_update}" != "true" ]]; then
    log_info "Using existing Bakery secret '${BAKERY_RACKSPACE_SECRET_NAME}' in namespace '${NAMESPACE}'."
    return
  fi

  if [[ -z "${BAKERY_RACKSPACE_URL}" || -z "${BAKERY_RACKSPACE_USERNAME}" || -z "${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    if [[ ! -t 0 ]]; then
      log_error "Bakery secret creation/update needs Rackspace Core credentials."
      log_error "Provide --bakery-rackspace-url/--bakery-rackspace-username/--bakery-rackspace-password or run interactively."
      exit 1
    fi
    prompt_for_missing_bakery_credentials
  fi

  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    log_info "Namespace '${NAMESPACE}' does not exist; creating it for Bakery secret setup..."
    kubectl create namespace "${NAMESPACE}" >/dev/null
  fi

  log_info "Creating/updating Bakery secret '${BAKERY_RACKSPACE_SECRET_NAME}' in namespace '${NAMESPACE}'."
  kubectl -n "${NAMESPACE}" create secret generic "${BAKERY_RACKSPACE_SECRET_NAME}" \
    --from-literal=rackspace-core-url="${BAKERY_RACKSPACE_URL}" \
    --from-literal=rackspace-core-username="${BAKERY_RACKSPACE_USERNAME}" \
    --from-literal=rackspace-core-password="${BAKERY_RACKSPACE_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

reject_conflicting_flags() {
  local arg=""
  for arg in "$@"; do
    case "${arg}" in
      --mode|--mode=*|--no-local-bakery|--enable-bakery|--bakery-db-integrated|--bakery-db-host|--bakery-db-host=*|--bakery-db-name|--bakery-db-name=*|--bakery-db-user|--bakery-db-user=*)
        echo "[ERROR] Option '${arg}' is not supported by install-bakery.sh." >&2
        echo "[ERROR] Bakery installer is fixed to bakery-only mode." >&2
        exit 1
        ;;
      --set=*|--set-string=*|--set-json=*|--set-literal=*|--set-file=*)
        if [[ "${arg}" == *"bakery.database.createServer=false"* ]]; then
          echo "[ERROR] bakery.database.createServer=false is not supported by install-bakery.sh." >&2
          exit 1
        fi
        if [[ "${arg}" == *"bakery.enabled=false"* ]]; then
          echo "[ERROR] bakery.enabled=false is not supported by install-bakery.sh." >&2
          exit 1
        fi
        if [[ "${arg}" == *"poundcake.enabled=true"* ]]; then
          echo "[ERROR] poundcake.enabled=true is not supported by install-bakery.sh." >&2
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
      if [[ "${next}" == *"bakery.enabled=false"* ]]; then
        echo "[ERROR] bakery.enabled=false is not supported by install-bakery.sh." >&2
        exit 1
      fi
      if [[ "${next}" == *"poundcake.enabled=true"* ]]; then
        echo "[ERROR] poundcake.enabled=true is not supported by install-bakery.sh." >&2
        exit 1
      fi
      i=$((i + 2))
      continue
    fi
    i=$((i + 1))
  done
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h)
        usage
        exit 0
        ;;
      --bakery-rackspace-secret-name)
        BAKERY_RACKSPACE_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-rackspace-secret-name=*)
        BAKERY_RACKSPACE_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-rackspace-url)
        BAKERY_RACKSPACE_URL="$2"
        shift 2
        ;;
      --bakery-rackspace-url=*)
        BAKERY_RACKSPACE_URL="${1#*=}"
        shift
        ;;
      --bakery-rackspace-username)
        BAKERY_RACKSPACE_USERNAME="$2"
        shift 2
        ;;
      --bakery-rackspace-username=*)
        BAKERY_RACKSPACE_USERNAME="${1#*=}"
        shift
        ;;
      --bakery-rackspace-password)
        BAKERY_RACKSPACE_PASSWORD="$2"
        shift 2
        ;;
      --bakery-rackspace-password=*)
        BAKERY_RACKSPACE_PASSWORD="${1#*=}"
        shift
        ;;
      --update-bakery-secret)
        UPDATE_BAKERY_SECRET="true"
        shift
        ;;
      --namespace|-n)
        NAMESPACE="$2"
        FORWARD_ARGS+=("$1" "$2")
        shift 2
        ;;
      --namespace=*)
        NAMESPACE="${1#*=}"
        FORWARD_ARGS+=("$1")
        shift
        ;;
      *)
        FORWARD_ARGS+=("$1")
        shift
        ;;
    esac
  done
}

for deprecated_env in \
  POUNDCAKE_BAKERY_DB_INTEGRATED \
  POUNDCAKE_BAKERY_DB_HOST \
  POUNDCAKE_BAKERY_DB_NAME \
  POUNDCAKE_BAKERY_DB_USER
do
  if [[ -n "${!deprecated_env:-}" ]]; then
    echo "[ERROR] ${deprecated_env} is not supported by install-bakery.sh." >&2
    echo "[ERROR] Bakery installer provisions MariaDB server resources with separate bakery schema/user." >&2
    exit 1
  fi
done

if [[ "${POUNDCAKE_NO_LOCAL_BAKERY:-false}" == "true" ]]; then
  echo "[ERROR] POUNDCAKE_NO_LOCAL_BAKERY=true is not supported by install-bakery.sh." >&2
  exit 1
fi

parse_args "$@"
UPDATE_BAKERY_SECRET="$(normalize_bool "${UPDATE_BAKERY_SECRET}")"
if [[ -z "${UPDATE_BAKERY_SECRET}" ]]; then
  log_error "POUNDCAKE_UPDATE_BAKERY_SECRET must be true or false."
  exit 1
fi
if (( ${#FORWARD_ARGS[@]} > 0 )); then
  reject_conflicting_flags "${FORWARD_ARGS[@]}"
else
  reject_conflicting_flags
fi

ensure_bakery_secret

INSTALL_CMD=(
  env
  POUNDCAKE_INSTALL_PROFILE=bakery
  POUNDCAKE_RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-bakery}"
  "${POUNDCAKE_INSTALLER}"
  --set poundcake.enabled=false
  --set bakery.enabled=true
  --set bakery.worker.enabled=true
  --set bakery.database.createServer=true
  --set-string "bakery.rackspaceCore.existingSecret=${BAKERY_RACKSPACE_SECRET_NAME}"
)
if (( ${#FORWARD_ARGS[@]} > 0 )); then
  INSTALL_CMD+=("${FORWARD_ARGS[@]}")
fi

exec "${INSTALL_CMD[@]}"

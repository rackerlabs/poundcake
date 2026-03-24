#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POUNDCAKE_INSTALLER="${SCRIPT_DIR}/install-poundcake.sh"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-bakery}"
BAKERY_ACTIVE_PROVIDER="${POUNDCAKE_BAKERY_ACTIVE_PROVIDER:-}"
BAKERY_RACKSPACE_SECRET_NAME="${POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME:-bakery-rackspace-core}"
BAKERY_RACKSPACE_URL="${POUNDCAKE_BAKERY_RACKSPACE_URL:-}"
BAKERY_RACKSPACE_USERNAME="${POUNDCAKE_BAKERY_RACKSPACE_USERNAME:-}"
BAKERY_RACKSPACE_PASSWORD="${POUNDCAKE_BAKERY_RACKSPACE_PASSWORD:-}"
BAKERY_SERVICENOW_SECRET_NAME="${POUNDCAKE_BAKERY_SERVICENOW_SECRET_NAME:-bakery-servicenow}"
BAKERY_SERVICENOW_URL="${POUNDCAKE_BAKERY_SERVICENOW_URL:-}"
BAKERY_SERVICENOW_USERNAME="${POUNDCAKE_BAKERY_SERVICENOW_USERNAME:-}"
BAKERY_SERVICENOW_PASSWORD="${POUNDCAKE_BAKERY_SERVICENOW_PASSWORD:-}"
BAKERY_JIRA_SECRET_NAME="${POUNDCAKE_BAKERY_JIRA_SECRET_NAME:-bakery-jira}"
BAKERY_JIRA_URL="${POUNDCAKE_BAKERY_JIRA_URL:-}"
BAKERY_JIRA_USERNAME="${POUNDCAKE_BAKERY_JIRA_USERNAME:-}"
BAKERY_JIRA_API_TOKEN="${POUNDCAKE_BAKERY_JIRA_API_TOKEN:-}"
BAKERY_GITHUB_SECRET_NAME="${POUNDCAKE_BAKERY_GITHUB_SECRET_NAME:-bakery-github}"
BAKERY_GITHUB_TOKEN="${POUNDCAKE_BAKERY_GITHUB_TOKEN:-}"
BAKERY_PAGERDUTY_SECRET_NAME="${POUNDCAKE_BAKERY_PAGERDUTY_SECRET_NAME:-bakery-pagerduty}"
BAKERY_PAGERDUTY_API_KEY="${POUNDCAKE_BAKERY_PAGERDUTY_API_KEY:-}"
BAKERY_TEAMS_SECRET_NAME="${POUNDCAKE_BAKERY_TEAMS_SECRET_NAME:-bakery-teams}"
BAKERY_TEAMS_WEBHOOK_URL="${POUNDCAKE_BAKERY_TEAMS_WEBHOOK_URL:-}"
BAKERY_DISCORD_SECRET_NAME="${POUNDCAKE_BAKERY_DISCORD_SECRET_NAME:-bakery-discord}"
BAKERY_DISCORD_WEBHOOK_URL="${POUNDCAKE_BAKERY_DISCORD_WEBHOOK_URL:-}"
BAKERY_AUTH_SECRET_NAME="${POUNDCAKE_BAKERY_AUTH_SECRET_NAME:-}"
BAKERY_HMAC_ACTIVE_KEY_ID="${POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY_ID:-}"
BAKERY_HMAC_ACTIVE_KEY="${POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY:-}"
BAKERY_HMAC_NEXT_KEY_ID="${POUNDCAKE_BAKERY_HMAC_NEXT_KEY_ID:-}"
BAKERY_HMAC_NEXT_KEY="${POUNDCAKE_BAKERY_HMAC_NEXT_KEY:-}"
UPDATE_BAKERY_SECRET="${POUNDCAKE_UPDATE_BAKERY_SECRET:-false}"
RACKSPACE_SECRET_READY="false"
SERVICENOW_SECRET_READY="false"
JIRA_SECRET_READY="false"
GITHUB_SECRET_READY="false"
PAGERDUTY_SECRET_READY="false"
TEAMS_SECRET_READY="false"
DISCORD_SECRET_READY="false"
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
  --bakery-active-provider <provider>     Active Bakery provider (default: rackspace_core)
  --bakery-rackspace-secret-name <name>   Secret name to verify/create (default: bakery-rackspace-core)
  --bakery-rackspace-url <url>            Rackspace Core URL for secret creation/update
  --bakery-rackspace-username <username>  Rackspace Core username for secret creation/update
  --bakery-rackspace-password <password>  Rackspace Core password for secret creation/update
  --bakery-servicenow-secret-name <name>  Secret name to verify/create (default: bakery-servicenow)
  --bakery-servicenow-url <url>           ServiceNow URL for secret creation/update
  --bakery-servicenow-username <user>     ServiceNow username for secret creation/update
  --bakery-servicenow-password <pass>     ServiceNow password for secret creation/update
  --bakery-jira-secret-name <name>        Secret name to verify/create (default: bakery-jira)
  --bakery-jira-url <url>                 Jira URL for secret creation/update
  --bakery-jira-username <user>           Jira username for secret creation/update
  --bakery-jira-api-token <token>         Jira API token for secret creation/update
  --bakery-github-secret-name <name>      Secret name to verify/create (default: bakery-github)
  --bakery-github-token <token>           GitHub token for secret creation/update
  --bakery-pagerduty-secret-name <name>   Secret name to verify/create (default: bakery-pagerduty)
  --bakery-pagerduty-api-key <key>        PagerDuty API key for secret creation/update
  --bakery-teams-secret-name <name>       Secret name to verify/create (default: bakery-teams)
  --bakery-teams-webhook-url <url>        Teams webhook URL for secret creation/update
  --bakery-discord-secret-name <name>     Secret name to verify/create (default: bakery-discord)
  --bakery-discord-webhook-url <url>      Discord webhook URL for secret creation/update
  --bakery-auth-secret-name <name>        Secret name for Bakery HMAC auth keys (default: release-derived)
  --update-bakery-secret                  Update existing secret (prompts for missing values)

Behavior:
  - If a provider secret exists, installer reuses it.
  - If provider credentials are supplied and the secret is missing, installer creates it.
  - Existing provider secrets are only updated when --update-bakery-secret is provided.
  - The active provider must have credentials from either a discovered secret or the credentials supplied for this run.
  - Bakery HMAC auth secret is auto-created when missing.
  - Default secret names come from values.yaml; installer only forwards secret-name overrides when you choose non-default names.
  - Bakery runtime settings such as active provider should live in values files or override files.

All remaining args are forwarded to install-poundcake.sh.
USAGE_EOF
}

default_bakery_auth_secret_name() {
  local release_name="$1"
  local fullname=""
  local bakery_name=""
  local secret_name=""

  if [[ "${release_name}" == *"poundcake"* ]]; then
    fullname="${release_name}"
  else
    fullname="${release_name}-poundcake"
  fi
  bakery_name="${fullname}-bakery"
  bakery_name="${bakery_name:0:63}"
  bakery_name="${bakery_name%-}"

  secret_name="${bakery_name}-secret"
  secret_name="${secret_name:0:63}"
  secret_name="${secret_name%-}"
  echo "${secret_name}"
}

generate_hmac_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi
  if command -v od >/dev/null 2>&1; then
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    return
  fi
  log_error "Cannot generate Bakery HMAC key (missing openssl and od)."
  exit 1
}

read_secret_literal() {
  local secret_name="$1"
  local key_name="$2"
  local encoded=""

  encoded="$(
    kubectl -n "${NAMESPACE}" get secret "${secret_name}" \
      -o jsonpath="{.data['${key_name}']}" 2>/dev/null || true
  )"
  if [[ -z "${encoded}" ]]; then
    echo ""
    return
  fi
  printf '%s' "${encoded}" | base64 --decode 2>/dev/null || true
}

provider_secret_exists() {
  local secret_name="$1"
  kubectl -n "${NAMESPACE}" get secret "${secret_name}" >/dev/null 2>&1
}

ensure_namespace_exists() {
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    log_info "Namespace '${NAMESPACE}' does not exist; creating it for Bakery secret setup..."
    kubectl create namespace "${NAMESPACE}" >/dev/null
  fi
}

get_var_value() {
  local var_name="$1"
  printf '%s' "${!var_name:-}"
}

set_var_value() {
  local var_name="$1"
  local var_value="$2"
  printf -v "${var_name}" '%s' "${var_value}"
}

prompt_required_value() {
  local value_var_name="$1"
  local prompt_label="$2"
  local hidden="${3:-false}"
  local current_value=""
  local input_value=""

  if [[ "${hidden}" == "true" ]]; then
    current_value="$(get_var_value "${value_var_name}")"
    while [[ -z "${current_value}" ]]; do
      read -r -s -p "${prompt_label}: " input_value
      echo
      set_var_value "${value_var_name}" "${input_value}"
      current_value="${input_value}"
    done
    return
  fi

  current_value="$(get_var_value "${value_var_name}")"
  while [[ -z "${current_value}" ]]; do
    read -r -p "${prompt_label}: " input_value
    set_var_value "${value_var_name}" "${input_value}"
    current_value="${input_value}"
  done
}

ensure_url_username_password_secret() {
  local display_name="$1"
  local secret_name="$2"
  local url_key="$3"
  local username_key="$4"
  local password_key="$5"
  local required="$6"
  local url_var_name="$7"
  local username_var_name="$8"
  local password_var_name="$9"
  local ready_var_name="${10}"
  local option_hint="${11}"
  local url_ref=""
  local username_ref=""
  local password_ref=""
  local secret_exists="false"
  local provided_values="false"

  set_var_value "${ready_var_name}" "false"
  url_ref="$(get_var_value "${url_var_name}")"
  username_ref="$(get_var_value "${username_var_name}")"
  password_ref="$(get_var_value "${password_var_name}")"
  if [[ -n "${url_ref}" || -n "${username_ref}" || -n "${password_ref}" ]]; then
    provided_values="true"
  fi

  if provider_secret_exists "${secret_name}"; then
    secret_exists="true"
  fi

  if [[ "${secret_exists}" == "true" && "${provided_values}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" ]]; then
    log_error "${display_name} secret '${secret_name}' already exists in namespace '${NAMESPACE}'."
    log_error "Use --update-bakery-secret to update it."
    exit 1
  fi

  if [[ "${provided_values}" != "true" && "${required}" != "true" ]]; then
    if [[ "${secret_exists}" == "true" ]]; then
      log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
      set_var_value "${ready_var_name}" "true"
    fi
    return
  fi

  if [[ "${secret_exists}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" && "${provided_values}" != "true" ]]; then
    log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
    set_var_value "${ready_var_name}" "true"
    return
  fi

  if [[ -z "${url_ref}" || -z "${username_ref}" || -z "${password_ref}" ]]; then
    if [[ ! -t 0 ]]; then
      log_error "${display_name} secret creation/update needs credentials."
      log_error "Provide ${option_hint} or run interactively."
      exit 1
    fi
    prompt_required_value "${url_var_name}" "${display_name} URL"
    prompt_required_value "${username_var_name}" "${display_name} Username"
    prompt_required_value "${password_var_name}" "${display_name} Password" "true"
  fi

  url_ref="$(get_var_value "${url_var_name}")"
  username_ref="$(get_var_value "${username_var_name}")"
  password_ref="$(get_var_value "${password_var_name}")"
  ensure_namespace_exists
  log_info "Creating/updating ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
  kubectl -n "${NAMESPACE}" create secret generic "${secret_name}" \
    --from-literal="${url_key}=${url_ref}" \
    --from-literal="${username_key}=${username_ref}" \
    --from-literal="${password_key}=${password_ref}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  set_var_value "${ready_var_name}" "true"
}

ensure_url_username_token_secret() {
  local display_name="$1"
  local secret_name="$2"
  local url_key="$3"
  local username_key="$4"
  local token_key="$5"
  local required="$6"
  local url_var_name="$7"
  local username_var_name="$8"
  local token_var_name="$9"
  local ready_var_name="${10}"
  local option_hint="${11}"
  local token_prompt_label="${12}"
  local url_ref=""
  local username_ref=""
  local token_ref=""
  local secret_exists="false"
  local provided_values="false"

  set_var_value "${ready_var_name}" "false"
  url_ref="$(get_var_value "${url_var_name}")"
  username_ref="$(get_var_value "${username_var_name}")"
  token_ref="$(get_var_value "${token_var_name}")"
  if [[ -n "${url_ref}" || -n "${username_ref}" || -n "${token_ref}" ]]; then
    provided_values="true"
  fi

  if provider_secret_exists "${secret_name}"; then
    secret_exists="true"
  fi

  if [[ "${secret_exists}" == "true" && "${provided_values}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" ]]; then
    log_error "${display_name} secret '${secret_name}' already exists in namespace '${NAMESPACE}'."
    log_error "Use --update-bakery-secret to update it."
    exit 1
  fi

  if [[ "${provided_values}" != "true" && "${required}" != "true" ]]; then
    if [[ "${secret_exists}" == "true" ]]; then
      log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
      set_var_value "${ready_var_name}" "true"
    fi
    return
  fi

  if [[ "${secret_exists}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" && "${provided_values}" != "true" ]]; then
    log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
    set_var_value "${ready_var_name}" "true"
    return
  fi

  if [[ -z "${url_ref}" || -z "${username_ref}" || -z "${token_ref}" ]]; then
    if [[ ! -t 0 ]]; then
      log_error "${display_name} secret creation/update needs credentials."
      log_error "Provide ${option_hint} or run interactively."
      exit 1
    fi
    prompt_required_value "${url_var_name}" "${display_name} URL"
    prompt_required_value "${username_var_name}" "${display_name} Username"
    prompt_required_value "${token_var_name}" "${token_prompt_label}" "true"
  fi

  url_ref="$(get_var_value "${url_var_name}")"
  username_ref="$(get_var_value "${username_var_name}")"
  token_ref="$(get_var_value "${token_var_name}")"
  ensure_namespace_exists
  log_info "Creating/updating ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
  kubectl -n "${NAMESPACE}" create secret generic "${secret_name}" \
    --from-literal="${url_key}=${url_ref}" \
    --from-literal="${username_key}=${username_ref}" \
    --from-literal="${token_key}=${token_ref}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  set_var_value "${ready_var_name}" "true"
}

ensure_single_value_secret() {
  local display_name="$1"
  local secret_name="$2"
  local secret_key="$3"
  local required="$4"
  local value_var_name="$5"
  local ready_var_name="$6"
  local prompt_label="$7"
  local option_hint="$8"
  local prompt_hidden="${9:-true}"
  local value_ref=""
  local secret_exists="false"
  local provided_values="false"

  set_var_value "${ready_var_name}" "false"
  value_ref="$(get_var_value "${value_var_name}")"
  if [[ -n "${value_ref}" ]]; then
    provided_values="true"
  fi

  if provider_secret_exists "${secret_name}"; then
    secret_exists="true"
  fi

  if [[ "${secret_exists}" == "true" && "${provided_values}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" ]]; then
    log_error "${display_name} secret '${secret_name}' already exists in namespace '${NAMESPACE}'."
    log_error "Use --update-bakery-secret to update it."
    exit 1
  fi

  if [[ "${provided_values}" != "true" && "${required}" != "true" ]]; then
    if [[ "${secret_exists}" == "true" ]]; then
      log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
      set_var_value "${ready_var_name}" "true"
    fi
    return
  fi

  if [[ "${secret_exists}" == "true" && "${UPDATE_BAKERY_SECRET}" != "true" && "${provided_values}" != "true" ]]; then
    log_info "Using existing ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
    set_var_value "${ready_var_name}" "true"
    return
  fi

  if [[ -z "${value_ref}" ]]; then
    if [[ ! -t 0 ]]; then
      log_error "${display_name} secret creation/update needs a credential value."
      log_error "Provide ${option_hint} or run interactively."
      exit 1
    fi
    prompt_required_value "${value_var_name}" "${prompt_label}" "${prompt_hidden}"
  fi

  value_ref="$(get_var_value "${value_var_name}")"
  ensure_namespace_exists
  log_info "Creating/updating ${display_name} secret '${secret_name}' in namespace '${NAMESPACE}'."
  kubectl -n "${NAMESPACE}" create secret generic "${secret_name}" \
    --from-literal="${secret_key}=${value_ref}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  set_var_value "${ready_var_name}" "true"
}

ensure_bakery_auth_secret() {
  local secret_exists="false"
  local provided_values="false"
  local existing_active_id=""
  local existing_active_key=""
  local existing_next_id=""
  local existing_next_key=""
  local active_id=""
  local active_key=""
  local next_id=""
  local next_key=""

  if [[ -z "${BAKERY_AUTH_SECRET_NAME}" ]]; then
    BAKERY_AUTH_SECRET_NAME="$(default_bakery_auth_secret_name "${RELEASE_NAME}")"
  fi

  if [[ -n "${BAKERY_HMAC_ACTIVE_KEY_ID}" || -n "${BAKERY_HMAC_ACTIVE_KEY}" || -n "${BAKERY_HMAC_NEXT_KEY_ID}" || -n "${BAKERY_HMAC_NEXT_KEY}" ]]; then
    provided_values="true"
  fi

  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    log_info "Namespace '${NAMESPACE}' does not exist; creating it for Bakery auth secret setup..."
    kubectl create namespace "${NAMESPACE}" >/dev/null
  fi

  if kubectl -n "${NAMESPACE}" get secret "${BAKERY_AUTH_SECRET_NAME}" >/dev/null 2>&1; then
    secret_exists="true"
    existing_active_id="$(read_secret_literal "${BAKERY_AUTH_SECRET_NAME}" "active-key-id")"
    existing_active_key="$(read_secret_literal "${BAKERY_AUTH_SECRET_NAME}" "active-key")"
    existing_next_id="$(read_secret_literal "${BAKERY_AUTH_SECRET_NAME}" "next-key-id")"
    existing_next_key="$(read_secret_literal "${BAKERY_AUTH_SECRET_NAME}" "next-key")"
  fi

  if [[ "${secret_exists}" == "true" && "${provided_values}" != "true" && -n "${existing_active_id}" && -n "${existing_active_key}" ]]; then
    log_info "Using existing Bakery HMAC auth secret '${BAKERY_AUTH_SECRET_NAME}' in namespace '${NAMESPACE}'."
    return
  fi

  active_id="${BAKERY_HMAC_ACTIVE_KEY_ID:-${existing_active_id:-active}}"
  active_key="${BAKERY_HMAC_ACTIVE_KEY:-${existing_active_key:-}}"
  next_id="${BAKERY_HMAC_NEXT_KEY_ID:-${existing_next_id:-}}"
  next_key="${BAKERY_HMAC_NEXT_KEY:-${existing_next_key:-}}"

  if [[ -z "${active_key}" ]]; then
    active_key="$(generate_hmac_key)"
  fi

  if [[ -n "${next_key}" && -z "${next_id}" ]]; then
    next_id="next"
  fi
  if [[ -n "${next_id}" && -z "${next_key}" ]]; then
    next_key="$(generate_hmac_key)"
  fi

  log_info "Creating/updating Bakery HMAC auth secret '${BAKERY_AUTH_SECRET_NAME}' in namespace '${NAMESPACE}'."
  kubectl -n "${NAMESPACE}" create secret generic "${BAKERY_AUTH_SECRET_NAME}" \
    --from-literal=active-key-id="${active_id}" \
    --from-literal=active-key="${active_key}" \
    --from-literal=next-key-id="${next_id}" \
    --from-literal=next-key="${next_key}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

ensure_provider_secrets() {
  local rackspace_required="false"
  local servicenow_required="false"
  local jira_required="false"
  local github_required="false"
  local pagerduty_required="false"
  local teams_required="false"
  local discord_required="false"

  case "${BAKERY_ACTIVE_PROVIDER}" in
    rackspace_core)
      rackspace_required="true"
      ;;
    servicenow)
      servicenow_required="true"
      ;;
    jira)
      jira_required="true"
      ;;
    github)
      github_required="true"
      ;;
    pagerduty)
      pagerduty_required="true"
      ;;
    teams)
      teams_required="true"
      ;;
    discord)
      discord_required="true"
      ;;
  esac

  ensure_url_username_password_secret \
    "Rackspace Core" \
    "${BAKERY_RACKSPACE_SECRET_NAME}" \
    "rackspace-core-url" \
    "rackspace-core-username" \
    "rackspace-core-password" \
    "${rackspace_required}" \
    BAKERY_RACKSPACE_URL \
    BAKERY_RACKSPACE_USERNAME \
    BAKERY_RACKSPACE_PASSWORD \
    RACKSPACE_SECRET_READY \
    "--bakery-rackspace-url/--bakery-rackspace-username/--bakery-rackspace-password"

  ensure_url_username_password_secret \
    "ServiceNow" \
    "${BAKERY_SERVICENOW_SECRET_NAME}" \
    "servicenow-url" \
    "servicenow-username" \
    "servicenow-password" \
    "${servicenow_required}" \
    BAKERY_SERVICENOW_URL \
    BAKERY_SERVICENOW_USERNAME \
    BAKERY_SERVICENOW_PASSWORD \
    SERVICENOW_SECRET_READY \
    "--bakery-servicenow-url/--bakery-servicenow-username/--bakery-servicenow-password"

  ensure_url_username_token_secret \
    "Jira" \
    "${BAKERY_JIRA_SECRET_NAME}" \
    "jira-url" \
    "jira-username" \
    "jira-api-token" \
    "${jira_required}" \
    BAKERY_JIRA_URL \
    BAKERY_JIRA_USERNAME \
    BAKERY_JIRA_API_TOKEN \
    JIRA_SECRET_READY \
    "--bakery-jira-url/--bakery-jira-username/--bakery-jira-api-token" \
    "Jira API Token"

  ensure_single_value_secret \
    "GitHub" \
    "${BAKERY_GITHUB_SECRET_NAME}" \
    "github-token" \
    "${github_required}" \
    BAKERY_GITHUB_TOKEN \
    GITHUB_SECRET_READY \
    "GitHub Token" \
    "--bakery-github-token" \
    "true"

  ensure_single_value_secret \
    "PagerDuty" \
    "${BAKERY_PAGERDUTY_SECRET_NAME}" \
    "pagerduty-api-key" \
    "${pagerduty_required}" \
    BAKERY_PAGERDUTY_API_KEY \
    PAGERDUTY_SECRET_READY \
    "PagerDuty API Key" \
    "--bakery-pagerduty-api-key" \
    "true"

  ensure_single_value_secret \
    "Teams" \
    "${BAKERY_TEAMS_SECRET_NAME}" \
    "teams-webhook-url" \
    "${teams_required}" \
    BAKERY_TEAMS_WEBHOOK_URL \
    TEAMS_SECRET_READY \
    "Teams Webhook URL" \
    "--bakery-teams-webhook-url" \
    "false"

  ensure_single_value_secret \
    "Discord" \
    "${BAKERY_DISCORD_SECRET_NAME}" \
    "discord-webhook-url" \
    "${discord_required}" \
    BAKERY_DISCORD_WEBHOOK_URL \
    DISCORD_SECRET_READY \
    "Discord Webhook URL" \
    "--bakery-discord-webhook-url" \
    "false"
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
      --bakery-active-provider)
        BAKERY_ACTIVE_PROVIDER="$2"
        shift 2
        ;;
      --bakery-active-provider=*)
        BAKERY_ACTIVE_PROVIDER="${1#*=}"
        shift
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
      --bakery-servicenow-secret-name)
        BAKERY_SERVICENOW_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-servicenow-secret-name=*)
        BAKERY_SERVICENOW_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-servicenow-url)
        BAKERY_SERVICENOW_URL="$2"
        shift 2
        ;;
      --bakery-servicenow-url=*)
        BAKERY_SERVICENOW_URL="${1#*=}"
        shift
        ;;
      --bakery-servicenow-username)
        BAKERY_SERVICENOW_USERNAME="$2"
        shift 2
        ;;
      --bakery-servicenow-username=*)
        BAKERY_SERVICENOW_USERNAME="${1#*=}"
        shift
        ;;
      --bakery-servicenow-password)
        BAKERY_SERVICENOW_PASSWORD="$2"
        shift 2
        ;;
      --bakery-servicenow-password=*)
        BAKERY_SERVICENOW_PASSWORD="${1#*=}"
        shift
        ;;
      --bakery-jira-secret-name)
        BAKERY_JIRA_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-jira-secret-name=*)
        BAKERY_JIRA_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-jira-url)
        BAKERY_JIRA_URL="$2"
        shift 2
        ;;
      --bakery-jira-url=*)
        BAKERY_JIRA_URL="${1#*=}"
        shift
        ;;
      --bakery-jira-username)
        BAKERY_JIRA_USERNAME="$2"
        shift 2
        ;;
      --bakery-jira-username=*)
        BAKERY_JIRA_USERNAME="${1#*=}"
        shift
        ;;
      --bakery-jira-api-token)
        BAKERY_JIRA_API_TOKEN="$2"
        shift 2
        ;;
      --bakery-jira-api-token=*)
        BAKERY_JIRA_API_TOKEN="${1#*=}"
        shift
        ;;
      --bakery-github-secret-name)
        BAKERY_GITHUB_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-github-secret-name=*)
        BAKERY_GITHUB_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-github-token)
        BAKERY_GITHUB_TOKEN="$2"
        shift 2
        ;;
      --bakery-github-token=*)
        BAKERY_GITHUB_TOKEN="${1#*=}"
        shift
        ;;
      --bakery-pagerduty-secret-name)
        BAKERY_PAGERDUTY_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-pagerduty-secret-name=*)
        BAKERY_PAGERDUTY_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-pagerduty-api-key)
        BAKERY_PAGERDUTY_API_KEY="$2"
        shift 2
        ;;
      --bakery-pagerduty-api-key=*)
        BAKERY_PAGERDUTY_API_KEY="${1#*=}"
        shift
        ;;
      --bakery-teams-secret-name)
        BAKERY_TEAMS_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-teams-secret-name=*)
        BAKERY_TEAMS_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-teams-webhook-url)
        BAKERY_TEAMS_WEBHOOK_URL="$2"
        shift 2
        ;;
      --bakery-teams-webhook-url=*)
        BAKERY_TEAMS_WEBHOOK_URL="${1#*=}"
        shift
        ;;
      --bakery-discord-secret-name)
        BAKERY_DISCORD_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-discord-secret-name=*)
        BAKERY_DISCORD_SECRET_NAME="${1#*=}"
        shift
        ;;
      --bakery-discord-webhook-url)
        BAKERY_DISCORD_WEBHOOK_URL="$2"
        shift 2
        ;;
      --bakery-discord-webhook-url=*)
        BAKERY_DISCORD_WEBHOOK_URL="${1#*=}"
        shift
        ;;
      --bakery-auth-secret-name)
        BAKERY_AUTH_SECRET_NAME="$2"
        shift 2
        ;;
      --bakery-auth-secret-name=*)
        BAKERY_AUTH_SECRET_NAME="${1#*=}"
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

if [[ -z "${BAKERY_ACTIVE_PROVIDER}" ]]; then
  BAKERY_ACTIVE_PROVIDER="rackspace_core"
fi

ensure_provider_secrets
ensure_bakery_auth_secret

INSTALL_CMD=(
  env
  POUNDCAKE_INSTALL_PROFILE=bakery
  POUNDCAKE_RELEASE_NAME="${RELEASE_NAME}"
  "${POUNDCAKE_INSTALLER}"
  --set poundcake.enabled=false
  --set bakery.enabled=true
  --set bakery.worker.enabled=true
  --set bakery.database.createServer=true
)

if [[ -n "${POUNDCAKE_BAKERY_ACTIVE_PROVIDER:-}" || "${BAKERY_ACTIVE_PROVIDER}" != "rackspace_core" ]]; then
  INSTALL_CMD+=(--set-string "bakery.config.activeProvider=${BAKERY_ACTIVE_PROVIDER}")
fi

if [[ "${BAKERY_AUTH_SECRET_NAME}" != "$(default_bakery_auth_secret_name "${RELEASE_NAME}")" ]]; then
  INSTALL_CMD+=(--set-string "bakery.auth.existingSecret=${BAKERY_AUTH_SECRET_NAME}")
  INSTALL_CMD+=(--set-string "bakery.client.auth.existingSecret=${BAKERY_AUTH_SECRET_NAME}")
fi

if [[ "${RACKSPACE_SECRET_READY}" == "true" && "${BAKERY_RACKSPACE_SECRET_NAME}" != "bakery-rackspace-core" ]]; then
  INSTALL_CMD+=(--set-string "bakery.rackspaceCore.existingSecret=${BAKERY_RACKSPACE_SECRET_NAME}")
fi
if [[ "${SERVICENOW_SECRET_READY}" == "true" && "${BAKERY_SERVICENOW_SECRET_NAME}" != "bakery-servicenow" ]]; then
  INSTALL_CMD+=(--set-string "bakery.servicenow.existingSecret=${BAKERY_SERVICENOW_SECRET_NAME}")
fi
if [[ "${JIRA_SECRET_READY}" == "true" && "${BAKERY_JIRA_SECRET_NAME}" != "bakery-jira" ]]; then
  INSTALL_CMD+=(--set-string "bakery.jira.existingSecret=${BAKERY_JIRA_SECRET_NAME}")
fi
if [[ "${GITHUB_SECRET_READY}" == "true" && "${BAKERY_GITHUB_SECRET_NAME}" != "bakery-github" ]]; then
  INSTALL_CMD+=(--set-string "bakery.github.existingSecret=${BAKERY_GITHUB_SECRET_NAME}")
fi
if [[ "${PAGERDUTY_SECRET_READY}" == "true" && "${BAKERY_PAGERDUTY_SECRET_NAME}" != "bakery-pagerduty" ]]; then
  INSTALL_CMD+=(--set-string "bakery.pagerduty.existingSecret=${BAKERY_PAGERDUTY_SECRET_NAME}")
fi
if [[ "${TEAMS_SECRET_READY}" == "true" && "${BAKERY_TEAMS_SECRET_NAME}" != "bakery-teams" ]]; then
  INSTALL_CMD+=(--set-string "bakery.teams.existingSecret=${BAKERY_TEAMS_SECRET_NAME}")
fi
if [[ "${DISCORD_SECRET_READY}" == "true" && "${BAKERY_DISCORD_SECRET_NAME}" != "bakery-discord" ]]; then
  INSTALL_CMD+=(--set-string "bakery.discord.existingSecret=${BAKERY_DISCORD_SECRET_NAME}")
fi
if (( ${#FORWARD_ARGS[@]} > 0 )); then
  INSTALL_CMD+=("${FORWARD_ARGS[@]}")
fi

exec "${INSTALL_CMD[@]}"

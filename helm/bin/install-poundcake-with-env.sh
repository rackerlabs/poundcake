#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
HELM_TIMEOUT="${POUNDCAKE_HELM_TIMEOUT:-120m}"
HELM_WAIT="${POUNDCAKE_HELM_WAIT:-false}"
HELM_ATOMIC="${POUNDCAKE_HELM_ATOMIC:-false}"
HELM_CLEANUP_ON_FAIL="${POUNDCAKE_HELM_CLEANUP_ON_FAIL:-false}"
ALLOW_HOOK_WAIT="${POUNDCAKE_ALLOW_HOOK_WAIT:-false}"

GHCR_OWNER="${POUNDCAKE_GHCR_OWNER:-rackerlabs}"
CHART_REPO="${POUNDCAKE_CHART_REPO:-}"
POUNDCAKE_IMAGE_REPO="${POUNDCAKE_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake}"
POUNDCAKE_IMAGE_TAG="${POUNDCAKE_IMAGE_TAG:-}"
POUNDCAKE_IMAGE_DIGEST="${POUNDCAKE_IMAGE_DIGEST:-}"
STACKSTORM_IMAGE_REPO="${POUNDCAKE_STACKSTORM_IMAGE_REPO:-stackstorm/st2}"
STACKSTORM_IMAGE_TAG="${POUNDCAKE_STACKSTORM_IMAGE_TAG:-3.9.0}"
UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-}"
UI_IMAGE_TAG="${POUNDCAKE_UI_IMAGE_TAG:-}"
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-}"
BAKERY_IMAGE_TAG="${POUNDCAKE_BAKERY_IMAGE_TAG:-${POUNDCAKE_IMAGE_TAG:-}}"
CHART_VERSION="${POUNDCAKE_CHART_VERSION:-}"
VERSION_FILE="${POUNDCAKE_VERSION_FILE:-}"
HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-}"
HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-}"
IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"
PACK_SYNC_ENDPOINT="${POUNDCAKE_PACK_SYNC_ENDPOINT:-http://poundcake-api:8000/api/v1/cook/packs}"

BASE_OVERRIDES="${POUNDCAKE_BASE_OVERRIDES:-/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml}"
GLOBAL_OVERRIDES_DIR="${POUNDCAKE_GLOBAL_OVERRIDES_DIR:-/etc/genestack/helm-configs/global_overrides}"
SERVICE_CONFIG_DIR="${POUNDCAKE_SERVICE_CONFIG_DIR:-/etc/genestack/helm-configs/poundcake}"
POST_RENDERER="${POUNDCAKE_HELM_POST_RENDERER:-/etc/genestack/kustomize/kustomize.sh}"
POST_RENDERER_ARGS="${POUNDCAKE_HELM_POST_RENDERER_ARGS:-poundcake/overlay}"
POST_RENDERER_OVERLAY_DIR="${POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR:-/etc/genestack/kustomize/poundcake/overlay}"

VALIDATE="${POUNDCAKE_HELM_VALIDATE:-false}"
INSTALL_DEBUG="${POUNDCAKE_INSTALL_DEBUG:-false}"
INSTALL_MODE="${POUNDCAKE_INSTALL_MODE:-full}"
OPERATOR_MODE="${POUNDCAKE_OPERATORS_MODE:-install-missing}"
MARIADB_OPERATOR_RELEASE_NAME="${POUNDCAKE_MARIADB_OPERATOR_RELEASE_NAME:-mariadb-operator}"
MARIADB_OPERATOR_NAMESPACE="${POUNDCAKE_MARIADB_OPERATOR_NAMESPACE:-mariadb-operator}"
MARIADB_OPERATOR_CHART_NAME="${POUNDCAKE_MARIADB_OPERATOR_CHART_NAME:-mariadb-operator}"
MARIADB_OPERATOR_CHART_REPO_URL="${POUNDCAKE_MARIADB_OPERATOR_CHART_REPO_URL:-https://mariadb-operator.github.io/mariadb-operator}"
MARIADB_OPERATOR_VERSION="${POUNDCAKE_MARIADB_OPERATOR_CHART_VERSION:-25.10.4}"
REDIS_OPERATOR_RELEASE_NAME="${POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME:-redis-operator}"
REDIS_OPERATOR_NAMESPACE="${POUNDCAKE_REDIS_OPERATOR_NAMESPACE:-redis-operator}"
REDIS_OPERATOR_CHART_NAME="${POUNDCAKE_REDIS_OPERATOR_CHART_NAME:-redis-operator}"
REDIS_OPERATOR_CHART_REPO_URL="${POUNDCAKE_REDIS_OPERATOR_CHART_REPO_URL:-https://ot-container-kit.github.io/helm-charts/}"
REDIS_OPERATOR_VERSION="${POUNDCAKE_REDIS_OPERATOR_CHART_VERSION:-0.23.0}"
RABBITMQ_OPERATOR_RELEASE_NAME="${POUNDCAKE_RABBITMQ_OPERATOR_RELEASE_NAME:-rabbitmq-cluster-operator}"
RABBITMQ_OPERATOR_NAMESPACE="${POUNDCAKE_RABBITMQ_OPERATOR_NAMESPACE:-rabbitmq-system}"
RABBITMQ_OPERATOR_CHART_NAME="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_NAME:-rabbitmq-cluster-operator}"
RABBITMQ_OPERATOR_CHART_REPO_URL="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_REPO_URL:-https://charts.bitnami.com/bitnami}"
RABBITMQ_OPERATOR_VERSION="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_VERSION:-4.4.34}"
BAKERY_RACKSPACE_URL="${POUNDCAKE_BAKERY_RACKSPACE_URL:-}"
BAKERY_RACKSPACE_USERNAME="${POUNDCAKE_BAKERY_RACKSPACE_USERNAME:-}"
BAKERY_RACKSPACE_PASSWORD="${POUNDCAKE_BAKERY_RACKSPACE_PASSWORD:-}"
BAKERY_RACKSPACE_SECRET_NAME="${POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME:-bakery-rackspace-core}"
SKIP_PREFLIGHT="false"
ROTATE_SECRETS="false"
INTERACTIVE_BAKERY_CREDS="false"
CURRENT_PHASE="initialization"
EXTRA_ARGS=()
BAKERY_SECRET_SET_ARGS=()

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_info() {
  printf '[%s] [INFO] %s\n' "$(timestamp_utc)" "$*"
}

log_warn() {
  printf '[%s] [WARN] %s\n' "$(timestamp_utc)" "$*" >&2
}

log_error() {
  printf '[%s] [ERROR] %s\n' "$(timestamp_utc)" "$*" >&2
}

log_phase() {
  CURRENT_PHASE="$*"
  log_info "Phase: ${CURRENT_PHASE}"
}

on_error() {
  local line_no="$1"
  local failed_command="$2"
  local exit_code="$3"
  trap - ERR
  log_error "Fatal: phase='${CURRENT_PHASE:-unknown}' line=${line_no} exit=${exit_code} cmd=${failed_command}"
  exit "${exit_code}"
}

trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR

usage() {
  cat <<'USAGE_EOF'
Usage:
  install-poundcake-with-env.sh [installer options] [helm upgrade/install args]

Installer options:
  --debug           Enable shell tracing for installer execution
  --validate        Run helm lint + helm template --debug before install
  --mode <full|bakery-only>  Install full stack or Bakery-only resources
  --operators-mode <install-missing|verify|skip>  Operator handling policy
  --verify-operators  Alias for --operators-mode verify
  --skip-operators    Alias for --operators-mode skip
  --skip-preflight  Skip dependency/cluster preflight checks
  --rotate-secrets  Delete known chart-managed secrets before install
  --interactive-bakery-creds Prompt for Bakery Rackspace Core credentials
  --bakery-rackspace-url <url>         Rackspace Core API URL
  --bakery-rackspace-username <user>   Rackspace Core username
  --bakery-rackspace-password <pass>   Rackspace Core password
  --bakery-rackspace-secret-name <name> Secret name for Rackspace credentials

Environment overrides:
  POUNDCAKE_GHCR_OWNER             (default: rackerlabs)
  POUNDCAKE_CHART_REPO             (default: local chart at ./helm)
  POUNDCAKE_CHART_VERSION          (optional; for OCI repo installs)
  POUNDCAKE_VERSION_FILE           (optional; explicit chart versions file)
  POUNDCAKE_BASE_OVERRIDES         (optional; base values file)
  POUNDCAKE_GLOBAL_OVERRIDES_DIR   (optional; global values dir)
  POUNDCAKE_SERVICE_CONFIG_DIR     (optional; service values dir)
  POUNDCAKE_HELM_POST_RENDERER     (optional; post-renderer script path)
  POUNDCAKE_HELM_POST_RENDERER_ARGS (optional; post-renderer args)
  POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR (optional; overlay path guard)
  POUNDCAKE_INSTALL_DEBUG         (default: false; same as --debug)
  POUNDCAKE_HELM_VALIDATE          (default: false; same as --validate)
  POUNDCAKE_IMAGE_REPO             (default: ghcr.io/${POUNDCAKE_GHCR_OWNER}/poundcake)
  POUNDCAKE_IMAGE_TAG              (optional; required when digest unset)
  POUNDCAKE_IMAGE_DIGEST           (optional; sha256:...; required when tag unset)
  POUNDCAKE_UI_IMAGE_REPO          (optional; sets uiImage.repository)
  POUNDCAKE_UI_IMAGE_TAG           (optional; sets uiImage.tag)
  POUNDCAKE_BAKERY_IMAGE_REPO      (optional; sets bakery.image.repository)
  POUNDCAKE_BAKERY_IMAGE_TAG       (optional; sets bakery.image.tag; defaults to POUNDCAKE_IMAGE_TAG)
  POUNDCAKE_INSTALL_MODE           (default: full; valid: full, bakery-only)
  POUNDCAKE_OPERATORS_MODE         (default: install-missing; valid: install-missing, verify, skip)
  POUNDCAKE_MARIADB_OPERATOR_RELEASE_NAME
  POUNDCAKE_MARIADB_OPERATOR_NAMESPACE
  POUNDCAKE_MARIADB_OPERATOR_CHART_NAME
  POUNDCAKE_MARIADB_OPERATOR_CHART_REPO_URL
  POUNDCAKE_MARIADB_OPERATOR_CHART_VERSION
  POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME
  POUNDCAKE_REDIS_OPERATOR_NAMESPACE
  POUNDCAKE_REDIS_OPERATOR_CHART_NAME
  POUNDCAKE_REDIS_OPERATOR_CHART_REPO_URL
  POUNDCAKE_REDIS_OPERATOR_CHART_VERSION
  POUNDCAKE_RABBITMQ_OPERATOR_RELEASE_NAME
  POUNDCAKE_RABBITMQ_OPERATOR_NAMESPACE
  POUNDCAKE_RABBITMQ_OPERATOR_CHART_NAME
  POUNDCAKE_RABBITMQ_OPERATOR_CHART_REPO_URL
  POUNDCAKE_RABBITMQ_OPERATOR_CHART_VERSION
  POUNDCAKE_BAKERY_RACKSPACE_URL   (optional; used to create/set bakery secret)
  POUNDCAKE_BAKERY_RACKSPACE_USERNAME (optional)
  POUNDCAKE_BAKERY_RACKSPACE_PASSWORD (optional)
  POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME (default: bakery-rackspace-core)
  HELM_REGISTRY_USERNAME           (optional; for OCI login)
  HELM_REGISTRY_PASSWORD           (optional; for OCI login)
  POUNDCAKE_IMAGE_PULL_SECRET_NAME     (default: ghcr-pull)
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET   (default: true)
  POUNDCAKE_IMAGE_PULL_SECRET_EMAIL    (default: noreply@local)
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED  (default: true)
  POUNDCAKE_PACK_SYNC_ENDPOINT     (default: http://poundcake-api:8000/api/v1/cook/packs)
  POUNDCAKE_RELEASE_NAME           (default: poundcake)
  POUNDCAKE_NAMESPACE              (default: rackspace)
  POUNDCAKE_HELM_TIMEOUT           (default: 120m)
  POUNDCAKE_HELM_WAIT              (default: false)
  POUNDCAKE_ALLOW_HOOK_WAIT        (default: false; required when forcing --wait/--atomic)
  POUNDCAKE_HELM_ATOMIC            (default: false)
  POUNDCAKE_HELM_CLEANUP_ON_FAIL   (default: false)

Examples:
  ./install/install-poundcake-helm.sh
  ./install/install-poundcake-helm.sh --validate
  ./install/install-poundcake-helm.sh --skip-preflight -f /path/to/values.yaml
USAGE_EOF
}

check_dependencies() {
  log_info "Checking required command dependencies..."
  local missing=0
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      log_error "Required command '$cmd' not found in PATH."
      missing=1
    fi
  done
  if [[ "$missing" -eq 1 ]]; then
    exit 1
  fi
}

check_cluster_connection() {
  log_info "Checking Kubernetes cluster connectivity..."
  if ! kubectl cluster-info >/dev/null 2>&1; then
    log_error "Cannot connect to Kubernetes cluster (kubectl cluster-info failed)."
    exit 1
  fi
}

perform_preflight_checks() {
  check_dependencies helm kubectl grep sed awk find sort
  check_cluster_connection
}

crd_exists() {
  local crd_name="$1"
  kubectl get crd "${crd_name}" >/dev/null 2>&1
}

crd_exists_any() {
  local crd_name=""
  for crd_name in "$@"; do
    if crd_exists "${crd_name}"; then
      return 0
    fi
  done
  return 1
}

install_or_verify_operator() {
  local operator_key="$1"
  local crd_names_raw="$2"
  local release_name="$3"
  local chart_name="$4"
  local chart_repo_url="$5"
  local chart_version="$6"
  local chart_namespace="$7"
  local crd_names=()
  local crd_name_display=""

  IFS=',' read -r -a crd_names <<< "${crd_names_raw}"
  crd_name_display="${crd_names[0]}"

  if crd_exists_any "${crd_names[@]}"; then
    log_info "Operator '${operator_key}' already present (CRD ${crd_name_display}); skipping install."
    return 0
  fi

  case "${OPERATOR_MODE}" in
    skip)
      log_info "Operator mode is skip. Not installing '${operator_key}' (missing CRD ${crd_name_display})."
      return 0
      ;;
    verify)
      log_error "Operator '${operator_key}' is missing (CRD ${crd_name_display})."
      log_error "Set --operators-mode install-missing to auto-install missing operators."
      exit 1
      ;;
    install-missing)
      log_info "Installing missing operator '${operator_key}' (chart ${chart_name}:${chart_version})..."
      helm upgrade --install "${release_name}" "${chart_name}" \
        --repo "${chart_repo_url}" \
        --version "${chart_version}" \
        --namespace "${chart_namespace}" \
        --create-namespace \
        --wait \
        --atomic \
        --cleanup-on-fail \
        --timeout "${HELM_TIMEOUT}"
      ;;
    *)
      log_error "Unsupported operators mode '${OPERATOR_MODE}'."
      exit 1
      ;;
  esac

  if ! crd_exists_any "${crd_names[@]}"; then
    log_error "Operator '${operator_key}' install completed but CRD ${crd_name_display} is still missing."
    exit 1
  fi
}

ensure_required_operators() {
  log_info "Operator mode: ${OPERATOR_MODE}"

  if [[ "${OPERATOR_MODE}" == "skip" ]]; then
    log_info "Skipping operator checks/installs."
    return 0
  fi

  install_or_verify_operator \
    "mariadb-operator" \
    "mariadbs.k8s.mariadb.com" \
    "${MARIADB_OPERATOR_RELEASE_NAME}" \
    "${MARIADB_OPERATOR_CHART_NAME}" \
    "${MARIADB_OPERATOR_CHART_REPO_URL}" \
    "${MARIADB_OPERATOR_VERSION}" \
    "${MARIADB_OPERATOR_NAMESPACE}"

  if [[ "${INSTALL_MODE}" == "full" ]]; then
    install_or_verify_operator \
      "redis-operator" \
      "redis.redis.redis.opstreelabs.in,redis.redis.opstreelabs.in" \
      "${REDIS_OPERATOR_RELEASE_NAME}" \
      "${REDIS_OPERATOR_CHART_NAME}" \
      "${REDIS_OPERATOR_CHART_REPO_URL}" \
      "${REDIS_OPERATOR_VERSION}" \
      "${REDIS_OPERATOR_NAMESPACE}"

    install_or_verify_operator \
      "rabbitmq-cluster-operator" \
      "rabbitmqclusters.rabbitmq.com" \
      "${RABBITMQ_OPERATOR_RELEASE_NAME}" \
      "${RABBITMQ_OPERATOR_CHART_NAME}" \
      "${RABBITMQ_OPERATOR_CHART_REPO_URL}" \
      "${RABBITMQ_OPERATOR_VERSION}" \
      "${RABBITMQ_OPERATOR_NAMESPACE}"
  fi
}

apply_bakery_rackspace_secret() {
  local should_manage_secret="false"

  if [[ "${INTERACTIVE_BAKERY_CREDS}" == "true" ]]; then
    should_manage_secret="true"
    local prompt_url_default="${BAKERY_RACKSPACE_URL:-https://ws.core.rackspace.com}"
    local prompt_user_default="${BAKERY_RACKSPACE_USERNAME:-}"
    local prompt_url=""
    local prompt_user=""
    local prompt_password=""

    read -r -p "Bakery Rackspace Core URL [${prompt_url_default}]: " prompt_url
    BAKERY_RACKSPACE_URL="${prompt_url:-${prompt_url_default}}"
    read -r -p "Bakery Rackspace Core username [${prompt_user_default}]: " prompt_user
    BAKERY_RACKSPACE_USERNAME="${prompt_user:-${prompt_user_default}}"
    read -r -s -p "Bakery Rackspace Core password: " prompt_password
    echo
    BAKERY_RACKSPACE_PASSWORD="${prompt_password}"
  fi

  if [[ -n "${BAKERY_RACKSPACE_URL}${BAKERY_RACKSPACE_USERNAME}${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    should_manage_secret="true"
  fi

  if [[ "${should_manage_secret}" != "true" ]]; then
    return 0
  fi

  if [[ -z "${BAKERY_RACKSPACE_URL}" || -z "${BAKERY_RACKSPACE_USERNAME}" || -z "${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    log_error "Bakery Rackspace Core credentials require URL, username, and password."
    log_error "Use --interactive-bakery-creds or provide all of:"
    log_error "  --bakery-rackspace-url --bakery-rackspace-username --bakery-rackspace-password"
    exit 1
  fi

  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    log_info "Namespace '${NAMESPACE}' does not exist; creating it for Bakery secret setup..."
    kubectl create namespace "${NAMESPACE}" >/dev/null
  fi

  log_info "Applying Bakery Rackspace Core secret '${BAKERY_RACKSPACE_SECRET_NAME}' in namespace '${NAMESPACE}'..."
  kubectl -n "${NAMESPACE}" create secret generic "${BAKERY_RACKSPACE_SECRET_NAME}" \
    --from-literal=rackspace-core-url="${BAKERY_RACKSPACE_URL}" \
    --from-literal=rackspace-core-username="${BAKERY_RACKSPACE_USERNAME}" \
    --from-literal=rackspace-core-password="${BAKERY_RACKSPACE_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f -

  BAKERY_SECRET_SET_ARGS+=(--set-string "bakery.enabled=true")
  BAKERY_SECRET_SET_ARGS+=(--set-string "bakery.rackspaceCore.existingSecret=${BAKERY_RACKSPACE_SECRET_NAME}")
}

ensure_oci_registry_auth() {
  local chart_source="$1"
  if [[ "${chart_source}" != oci://* ]]; then
    return
  fi

  local registry_host
  registry_host="$(echo "${chart_source}" | sed -E 's#^oci://([^/]+)/.*#\1#')"

  local username password
  username="${HELM_REGISTRY_USERNAME:-${GHCR_USERNAME:-${GITHUB_ACTOR:-}}}"
  password="${HELM_REGISTRY_PASSWORD:-${GHCR_TOKEN:-${CR_PAT:-${GITHUB_TOKEN:-}}}}"

  if [[ -n "${username}" && -n "${password}" ]]; then
    log_info "Authenticating Helm OCI client to ${registry_host} as ${username}..."
    printf '%s' "${password}" | helm registry login "${registry_host}" -u "${username}" --password-stdin >/dev/null
  else
    log_warn "${chart_source} is OCI-based. Set HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD for private charts."
  fi
}

collect_yaml_files() {
  local directory="$1"
  if [[ -d "${directory}" ]]; then
    find "${directory}" -maxdepth 1 -type f -name '*.yaml' | LC_ALL=C sort
  fi
  return 0
}

get_chart_version_from_file() {
  local version_file="$1"
  local chart_name="$2"

  awk -v chart="${chart_name}" '
    BEGIN { in_charts = 0 }
    /^[[:space:]]*charts:[[:space:]]*$/ { in_charts = 1; next }
    in_charts == 1 {
      if ($0 ~ /^[^[:space:]]/) { in_charts = 0; next }
      line = $0
      sub(/^[[:space:]]+/, "", line)
      if (line ~ ("^" chart ":[[:space:]]*")) {
        sub("^" chart ":[[:space:]]*", "", line)
        gsub(/[[:space:]]*$/, "", line)
        print line
        exit
      }
    }
  ' "${version_file}" | head -n1
}

resolve_chart_version() {
  if [[ -n "${CHART_VERSION}" ]]; then
    log_info "Using chart version from POUNDCAKE_CHART_VERSION: ${CHART_VERSION}"
    return
  fi

  local candidate_files=()
  if [[ -n "${VERSION_FILE}" ]]; then
    candidate_files+=("${VERSION_FILE}")
  fi
  candidate_files+=(
    "/etc/genestack/helm-chart-version.yaml"
    "/etc/genestack/helm-chart-versions.yaml"
  )

  local candidate
  for candidate in "${candidate_files[@]}"; do
    [[ -f "${candidate}" ]] || continue

    log_info "Inspecting chart version file: ${candidate}"
    CHART_VERSION="$(get_chart_version_from_file "${candidate}" "poundcake")"
    if [[ -z "${CHART_VERSION}" ]]; then
      local matched_line=""
      matched_line="$(grep -E '^[[:space:]]*poundcake:[[:space:]]*' "${candidate}" | head -n1 || true)"
      if [[ -n "${matched_line}" ]]; then
        CHART_VERSION="${matched_line#*:}"
        CHART_VERSION="$(echo "${CHART_VERSION}" | sed -E 's/^[[:space:]]*//; s/[[:space:]]*$//')"
      else
        log_warn "No poundcake version entry in ${candidate}; continuing without explicit --version."
      fi
    fi

    if [[ -n "${CHART_VERSION}" ]]; then
      log_info "Resolved chart version '${CHART_VERSION}' from ${candidate}"
      return
    fi
  done

  log_info "No chart version override resolved from configured version files."
}

run_helm_validation() {
  local chart_source="$1"
  local namespace="$2"
  local release_name="$3"
  shift 3
  local template_args=("$@")
  local lint_args=()

  local i=0
  while [[ $i -lt ${#template_args[@]} ]]; do
    local arg="${template_args[$i]}"
    if [[ "${arg}" == "--post-renderer" || "${arg}" == "--post-renderer-args" || "${arg}" == "--namespace" || "${arg}" == "--timeout" || "${arg}" == "--version" ]]; then
      ((i+=2))
      continue
    fi
    if [[ "${arg}" == "--create-namespace" || "${arg}" == "--wait" || "${arg}" == "--atomic" || "${arg}" == "--cleanup-on-fail" ]]; then
      ((i+=1))
      continue
    fi
    lint_args+=("${arg}")
    ((i+=1))
  done

  local lint_chart_source="${chart_source}"
  local tmpdir=""
  if [[ "${chart_source}" == oci://* ]]; then
    tmpdir="$(mktemp -d)"
    local pull_cmd=(helm pull "${chart_source}" --untar --untardir "${tmpdir}")
    if [[ -n "${CHART_VERSION}" ]]; then
      pull_cmd+=(--version "${CHART_VERSION}")
    fi
    "${pull_cmd[@]}"
    lint_chart_source="$(find "${tmpdir}" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  fi

  log_info "Running helm lint..."
  helm lint "${lint_chart_source}" "${lint_args[@]}"

  log_info "Running helm template --debug..."
  helm template "${release_name}" "${chart_source}" \
    --namespace "${namespace}" \
    "${template_args[@]}" \
    --debug >/dev/null

  if [[ -n "${tmpdir}" ]]; then
    rm -rf "${tmpdir}"
  fi
}

rotate_chart_secrets() {
  local namespace="$1"
  local release_name="$2"

  local secrets=(
    "${release_name}-poundcake-admin"
    "${release_name}-poundcake-stackstorm"
    "${release_name}-stackstorm-ha-st2-apikeys"
    "${release_name}-poundcake-mariadb-root"
    "${release_name}-poundcake-mariadb-user"
    "st2-st2-apikeys"
    "st2-mongodb-secret"
    "st2-rabbitmq"
    "poundcake-st2-auth"
  )

  log_info "Rotating selected chart-managed secrets (if present)..."
  local s
  for s in "${secrets[@]}"; do
    kubectl -n "${namespace}" delete secret "${s}" --ignore-not-found >/dev/null || true
  done
}

validate_image_pin_input() {
  if [[ "${INSTALL_MODE}" == "bakery-only" ]]; then
    if [[ -n "${POUNDCAKE_IMAGE_TAG}" && -n "${POUNDCAKE_IMAGE_DIGEST}" ]]; then
      log_error "Set only one of POUNDCAKE_IMAGE_TAG or POUNDCAKE_IMAGE_DIGEST."
      exit 1
    fi
    if [[ -n "${POUNDCAKE_IMAGE_DIGEST}" ]] && [[ ! "${POUNDCAKE_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      log_error "POUNDCAKE_IMAGE_DIGEST must match sha256:<64-hex>."
      exit 1
    fi
    return
  fi

  if [[ -n "${POUNDCAKE_IMAGE_TAG}" && -n "${POUNDCAKE_IMAGE_DIGEST}" ]]; then
    log_error "Set only one of POUNDCAKE_IMAGE_TAG or POUNDCAKE_IMAGE_DIGEST."
    exit 1
  fi
  if [[ -z "${POUNDCAKE_IMAGE_TAG}" && -z "${POUNDCAKE_IMAGE_DIGEST}" ]]; then
    log_error "Image pin required: set POUNDCAKE_IMAGE_TAG or POUNDCAKE_IMAGE_DIGEST."
    exit 1
  fi
  if [[ -n "${POUNDCAKE_IMAGE_DIGEST}" ]] && [[ ! "${POUNDCAKE_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    log_error "POUNDCAKE_IMAGE_DIGEST must match sha256:<64-hex>."
    exit 1
  fi
}

verify_rendered_endpoint_contract() {
  local rendered_manifest="$1"
  local expected_pack_sync_endpoint="$2"
  local canonical_pack_sync_endpoint="http://poundcake-api:8000/api/v1/cook/packs"

  if ! awk '
    BEGIN { kind=""; name=""; inmeta=0; want=0; probe=""; ready=0; live=0 }
    /^kind:[[:space:]]+/ { kind=$2; next }
    /^metadata:[[:space:]]*$/ { inmeta=1; next }
    inmeta && /^  name:[[:space:]]+/ {
      name=$2
      inmeta=0
      if (kind=="Deployment" && name=="poundcake-api") {
        want=1
      }
      next
    }
    want && /^[[:space:]]+readinessProbe:[[:space:]]*$/ { probe="ready"; next }
    want && /^[[:space:]]+livenessProbe:[[:space:]]*$/ { probe="live"; next }
    want && probe=="ready" && /^[[:space:]]+path:[[:space:]]*\/api\/v1\/ready[[:space:]]*$/ { ready=1; next }
    want && probe=="live" && /^[[:space:]]+path:[[:space:]]*\/api\/v1\/live[[:space:]]*$/ { live=1; next }
    /^---[[:space:]]*$/ { kind=""; name=""; inmeta=0; want=0; probe="" }
    END { exit((ready && live) ? 0 : 1) }
  ' "${rendered_manifest}"; then
    log_error "Rendered manifest contract failed: poundcake-api probes must target /api/v1/ready and /api/v1/live."
    exit 1
  fi

  if ! grep -Fq "${expected_pack_sync_endpoint}" "${rendered_manifest}"; then
    log_error "Rendered manifest contract failed: pack sync endpoint '${expected_pack_sync_endpoint}' not found."
    exit 1
  fi

  if [[ "${expected_pack_sync_endpoint}" != "${canonical_pack_sync_endpoint}" ]]; then
    log_warn "Using non-canonical pack sync endpoint override: ${expected_pack_sync_endpoint}"
  fi
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

log_phase "argument parsing"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)
      INSTALL_DEBUG="true"
      shift
      ;;
    --validate)
      VALIDATE="true"
      shift
      ;;
    --mode)
      INSTALL_MODE="$2"
      shift 2
      ;;
    --operators-mode)
      OPERATOR_MODE="$2"
      shift 2
      ;;
    --skip-operators)
      OPERATOR_MODE="skip"
      shift
      ;;
    --verify-operators)
      OPERATOR_MODE="verify"
      shift
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT="true"
      shift
      ;;
    --rotate-secrets)
      ROTATE_SECRETS="true"
      shift
      ;;
    --interactive-bakery-creds|--interactive-bakery-credentials)
      INTERACTIVE_BAKERY_CREDS="true"
      shift
      ;;
    --bakery-rackspace-url)
      BAKERY_RACKSPACE_URL="$2"
      shift 2
      ;;
    --bakery-rackspace-username)
      BAKERY_RACKSPACE_USERNAME="$2"
      shift 2
      ;;
    --bakery-rackspace-password)
      BAKERY_RACKSPACE_PASSWORD="$2"
      shift 2
      ;;
    --bakery-rackspace-secret-name)
      BAKERY_RACKSPACE_SECRET_NAME="$2"
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "${INSTALL_MODE}" != "full" && "${INSTALL_MODE}" != "bakery-only" ]]; then
  log_error "Invalid install mode '${INSTALL_MODE}'. Valid values: full, bakery-only."
  exit 1
fi

if [[ "${OPERATOR_MODE}" != "install-missing" && "${OPERATOR_MODE}" != "verify" && "${OPERATOR_MODE}" != "skip" ]]; then
  log_error "Invalid operators mode '${OPERATOR_MODE}'. Valid values: install-missing, verify, skip."
  exit 1
fi

if [[ "${INSTALL_DEBUG}" == "true" ]]; then
  log_info "Debug tracing enabled."
  PS4='+ [${BASH_SOURCE##*/}:${LINENO}${FUNCNAME[0]:+:${FUNCNAME[0]}}] '
  set -x
fi

log_info "Installer options: mode=${INSTALL_MODE}, operators_mode=${OPERATOR_MODE}, validate=${VALIDATE}, skip_preflight=${SKIP_PREFLIGHT}, rotate_secrets=${ROTATE_SECRETS}, debug=${INSTALL_DEBUG}"

log_phase "preflight checks"
if [[ "${SKIP_PREFLIGHT}" != "true" ]]; then
  perform_preflight_checks
else
  log_info "Skipping preflight checks (--skip-preflight)."
fi

log_phase "image pin validation"
validate_image_pin_input

if [[ "${CREATE_IMAGE_PULL_SECRET}" == "true" ]] && ! command -v kubectl >/dev/null 2>&1; then
  log_error "kubectl is required when POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true."
  exit 1
fi

log_phase "chart source and version resolution"
if [[ -z "${CHART_REPO}" ]]; then
  CHART_SOURCE="${CHART_DIR}"
else
  CHART_SOURCE="${CHART_REPO}"
fi

resolve_chart_version

log_phase "operator verification/install"
ensure_required_operators

log_phase "oci authentication"
ensure_oci_registry_auth "${CHART_SOURCE}"

wait_requested="false"
if [[ "${HELM_WAIT}" == "true" || "${HELM_ATOMIC}" == "true" ]]; then
  wait_requested="true"
fi
if (( ${#EXTRA_ARGS[@]} )); then
  for arg in "${EXTRA_ARGS[@]}"; do
    if [[ "${arg}" == "--wait" || "${arg}" == "--atomic" ]]; then
      wait_requested="true"
      break
    fi
  done
fi

if [[ "${wait_requested}" == "true" && "${ALLOW_HOOK_WAIT}" != "true" ]]; then
  log_error "Startup jobs are Helm post-install/post-upgrade hooks and workload init containers are marker-gated."
  log_error "Using --wait/--atomic can deadlock before hook jobs run, so jobs may never be created."
  log_error "Re-run with POUNDCAKE_HELM_WAIT=false (recommended)."
  log_error "If you intentionally want wait semantics, set POUNDCAKE_ALLOW_HOOK_WAIT=true."
  exit 1
fi

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" && -z "${IMAGE_PULL_SECRET_NAME}" ]]; then
  log_error "POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true requires POUNDCAKE_IMAGE_PULL_SECRET_NAME."
  exit 1
fi

log_phase "image pull secret configuration"
if [[ "${CREATE_IMAGE_PULL_SECRET}" == "true" ]]; then
  if [[ -z "${HELM_REGISTRY_USERNAME}" || -z "${HELM_REGISTRY_PASSWORD}" ]]; then
    log_error "POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true requires HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD."
    exit 1
  fi
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    log_info "Namespace '${NAMESPACE}' does not exist; creating it for image pull secret setup..."
    kubectl create namespace "${NAMESPACE}"
  fi
  log_info "Creating/updating image pull secret '${IMAGE_PULL_SECRET_NAME}' in namespace '${NAMESPACE}'..."
  kubectl -n "${NAMESPACE}" create secret docker-registry "${IMAGE_PULL_SECRET_NAME}" \
    --docker-server=ghcr.io \
    --docker-username="${HELM_REGISTRY_USERNAME}" \
    --docker-password="${HELM_REGISTRY_PASSWORD}" \
    --docker-email="${IMAGE_PULL_SECRET_EMAIL}" \
    --dry-run=client -o yaml | kubectl apply -f -
else
  log_info "Skipping image pull secret creation (POUNDCAKE_CREATE_IMAGE_PULL_SECRET=${CREATE_IMAGE_PULL_SECRET})."
fi

log_phase "bakery credential secret configuration"
apply_bakery_rackspace_secret

if [[ "${ROTATE_SECRETS}" == "true" ]]; then
  log_phase "secret rotation"
  rotate_chart_secrets "${NAMESPACE}" "${RELEASE_NAME}"
fi

log_phase "values file discovery"
OVERRIDE_ARGS=()
if [[ -n "${BASE_OVERRIDES}" && -f "${BASE_OVERRIDES}" ]]; then
  OVERRIDE_ARGS+=("-f" "${BASE_OVERRIDES}")
fi

while IFS= read -r yaml_file; do
  [[ -n "${yaml_file}" ]] || continue
  OVERRIDE_ARGS+=("-f" "${yaml_file}")
done < <(collect_yaml_files "${GLOBAL_OVERRIDES_DIR}")

while IFS= read -r yaml_file; do
  [[ -n "${yaml_file}" ]] || continue
  OVERRIDE_ARGS+=("-f" "${yaml_file}")
done < <(collect_yaml_files "${SERVICE_CONFIG_DIR}")

log_info "Resolved override file argument count: ${#OVERRIDE_ARGS[@]}"

POST_RENDER_ARGS=()
if [[ "${INSTALL_MODE}" != "bakery-only" && -f "${POST_RENDERER}" && -d "${POST_RENDERER_OVERLAY_DIR}" ]]; then
  POST_RENDER_ARGS+=("--post-renderer" "${POST_RENDERER}")
  if [[ -n "${POST_RENDERER_ARGS}" ]]; then
    POST_RENDER_ARGS+=("--post-renderer-args" "${POST_RENDERER_ARGS}")
  fi
fi

INSTALLER_SET_ARGS=(
  --set-string "deployment.mode=${INSTALL_MODE}"
  --set-string "poundcakeImage.repository=${POUNDCAKE_IMAGE_REPO}"
  --set-string "stackstormImage.repository=${STACKSTORM_IMAGE_REPO}"
  --set-string "stackstormImage.tag=${STACKSTORM_IMAGE_TAG}"
  --set-string "stackstormPackSync.endpoint=${PACK_SYNC_ENDPOINT}"
)

if [[ "${INSTALL_MODE}" == "bakery-only" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "bakery.enabled=true")
fi

if [[ -n "${POUNDCAKE_IMAGE_DIGEST}" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "poundcakeImage.tag=")
  INSTALLER_SET_ARGS+=(--set-string "poundcakeImage.digest=${POUNDCAKE_IMAGE_DIGEST}")
else
  INSTALLER_SET_ARGS+=(--set-string "poundcakeImage.tag=${POUNDCAKE_IMAGE_TAG}")
  INSTALLER_SET_ARGS+=(--set-string "poundcakeImage.digest=")
fi

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "poundcakeImage.pullSecrets[0]=${IMAGE_PULL_SECRET_NAME}")
  INSTALLER_SET_ARGS+=(--set-string "imagePullSecrets[0].name=${IMAGE_PULL_SECRET_NAME}")
fi

if [[ -n "${UI_IMAGE_REPO}" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "uiImage.repository=${UI_IMAGE_REPO}")
fi
if [[ -n "${UI_IMAGE_TAG}" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "uiImage.tag=${UI_IMAGE_TAG}")
fi
if [[ -n "${BAKERY_IMAGE_REPO}" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "bakery.image.repository=${BAKERY_IMAGE_REPO}")
fi
if [[ -n "${BAKERY_IMAGE_TAG}" ]]; then
  INSTALLER_SET_ARGS+=(--set-string "bakery.image.tag=${BAKERY_IMAGE_TAG}")
fi
if (( ${#BAKERY_SECRET_SET_ARGS[@]} )); then
  INSTALLER_SET_ARGS+=("${BAKERY_SECRET_SET_ARGS[@]}")
fi

COMMON_HELM_ARGS=(
  --namespace "${NAMESPACE}"
  --timeout "${HELM_TIMEOUT}"
)

if (( ${#OVERRIDE_ARGS[@]} )); then
  COMMON_HELM_ARGS+=("${OVERRIDE_ARGS[@]}")
fi
if (( ${#POST_RENDER_ARGS[@]} )); then
  COMMON_HELM_ARGS+=("${POST_RENDER_ARGS[@]}")
fi
if (( ${#INSTALLER_SET_ARGS[@]} )); then
  COMMON_HELM_ARGS+=("${INSTALLER_SET_ARGS[@]}")
fi

if [[ -n "${CHART_VERSION}" ]]; then
  COMMON_HELM_ARGS+=(--version "${CHART_VERSION}")
fi

if [[ "${VALIDATE}" == "true" ]]; then
  log_phase "helm validation"
  if (( ${#EXTRA_ARGS[@]} )); then
    run_helm_validation "${CHART_SOURCE}" "${NAMESPACE}" "${RELEASE_NAME}" \
      "${COMMON_HELM_ARGS[@]}" \
      "${EXTRA_ARGS[@]}"
  else
    run_helm_validation "${CHART_SOURCE}" "${NAMESPACE}" "${RELEASE_NAME}" \
      "${COMMON_HELM_ARGS[@]}"
  fi
fi

log_phase "helm command assembly"
HELM_CMD=(
  helm upgrade --install "${RELEASE_NAME}" "${CHART_SOURCE}"
  --create-namespace
  "${COMMON_HELM_ARGS[@]}"
)

if [[ "${HELM_WAIT}" == "true" ]]; then
  HELM_CMD+=(--wait)
fi
if [[ "${HELM_ATOMIC}" == "true" ]]; then
  HELM_CMD+=(--atomic)
fi
if [[ "${HELM_CLEANUP_ON_FAIL}" == "true" ]]; then
  HELM_CMD+=(--cleanup-on-fail)
fi

log_phase "rendered manifest contract verification"
TEMPLATE_ARGS=()
if (( ${#EXTRA_ARGS[@]} )); then
  for arg in "${EXTRA_ARGS[@]}"; do
    case "${arg}" in
      --wait|--atomic|--cleanup-on-fail|--create-namespace)
        continue
        ;;
    esac
    TEMPLATE_ARGS+=("${arg}")
  done
fi

RENDERED_MANIFEST="$(mktemp)"
HELM_TEMPLATE_CMD=(
  helm template "${RELEASE_NAME}" "${CHART_SOURCE}"
  "${COMMON_HELM_ARGS[@]}"
)

if (( ${#TEMPLATE_ARGS[@]} )); then
  "${HELM_TEMPLATE_CMD[@]}" "${TEMPLATE_ARGS[@]}" > "${RENDERED_MANIFEST}"
else
  "${HELM_TEMPLATE_CMD[@]}" > "${RENDERED_MANIFEST}"
fi

if [[ "${INSTALL_MODE}" != "bakery-only" ]]; then
  verify_rendered_endpoint_contract "${RENDERED_MANIFEST}" "${PACK_SYNC_ENDPOINT}"

  if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
    if ! awk -v secret_name="${IMAGE_PULL_SECRET_NAME}" '
      BEGIN {kind=""; name=""; want=0; seen=0; found=0}
      /^kind:[[:space:]]+/ {kind=$2}
      /^metadata:[[:space:]]*$/ {inmeta=1; next}
      inmeta && /^  name:[[:space:]]+/ {
        name=$2
        inmeta=0
        if ((kind == "Deployment" && name ~ /^poundcake-/) || (kind == "Job" && name == "poundcake-bootstrap")) {
          want=1
        }
        next
      }
      want && /^[[:space:]]+imagePullSecrets:[[:space:]]*$/ {in_pull=1; next}
      want && in_pull && /^[[:space:]]+-[[:space:]]+name:[[:space:]]+/ {
        if ($3 == secret_name || $3 == "\"" secret_name "\"") {
          found=1
        }
      }
      /^---[[:space:]]*$/ {
        if (want && found) {
          seen=1
        }
        kind=""; name=""; want=0; in_pull=0; found=0; inmeta=0
      }
      END {
        if (want && found) {
          seen=1
        }
        exit(seen ? 0 : 1)
      }
    ' "${RENDERED_MANIFEST}"; then
      log_error "Rendered PoundCake manifests do not include imagePullSecrets '${IMAGE_PULL_SECRET_NAME}'."
      log_error "Refusing install to avoid anonymous private-registry pulls."
      rm -f "${RENDERED_MANIFEST}"
      exit 1
    fi
  fi
fi
rm -f "${RENDERED_MANIFEST}"

log_phase "helm install execution"
log_info "Installing PoundCake release: ${RELEASE_NAME}"
log_info "Namespace: ${NAMESPACE}"
log_info "Install mode: ${INSTALL_MODE}"
log_info "Chart source: ${CHART_SOURCE}"
if [[ "${CHART_SOURCE}" == oci://* ]]; then
  log_info "Chart version: ${CHART_VERSION:-"(not set)"}"
fi
if [[ -n "${POUNDCAKE_IMAGE_DIGEST}" ]]; then
  log_info "PoundCake image: ${POUNDCAKE_IMAGE_REPO}@${POUNDCAKE_IMAGE_DIGEST}"
else
  log_info "PoundCake image: ${POUNDCAKE_IMAGE_REPO}:${POUNDCAKE_IMAGE_TAG}"
fi
log_info "Pack sync endpoint: ${PACK_SYNC_ENDPOINT}"
if [[ -n "${UI_IMAGE_REPO}" ]]; then
  log_info "UI image repo override: ${UI_IMAGE_REPO}"
fi
if [[ -n "${UI_IMAGE_TAG}" ]]; then
  log_info "UI image tag override: ${UI_IMAGE_TAG}"
fi
if [[ -n "${BAKERY_IMAGE_REPO}" ]]; then
  log_info "Bakery image repo override: ${BAKERY_IMAGE_REPO}"
fi
if [[ -n "${BAKERY_IMAGE_TAG}" ]]; then
  log_info "Bakery image tag override: ${BAKERY_IMAGE_TAG}"
fi
if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  log_info "Image pull secret injection: enabled (${IMAGE_PULL_SECRET_NAME})"
  log_info "Image pull secret key: poundcakeImage.pullSecrets"
else
  log_info "Image pull secret injection: disabled (POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=${IMAGE_PULL_SECRET_ENABLED})"
fi

log_info "Executing Helm command:"
printf '%q ' "${HELM_CMD[@]}"
if (( ${#EXTRA_ARGS[@]} )); then
  printf '%q ' "${EXTRA_ARGS[@]}"
fi
echo

if (( ${#EXTRA_ARGS[@]} )); then
  "${HELM_CMD[@]}" "${EXTRA_ARGS[@]}"
else
  "${HELM_CMD[@]}"
fi

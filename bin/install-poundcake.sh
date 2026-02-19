#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HELM_ROOT="${PROJECT_ROOT}/helm"

HELM_TIMEOUT_DEFAULT="${HELM_TIMEOUT_DEFAULT:-120m}"

check_dependencies() {
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: required command '$cmd' not found in PATH." >&2
      exit 1
    fi
  done
}

check_cluster_connection() {
  if ! kubectl cluster-info >/dev/null 2>&1; then
    echo "Error: cannot connect to Kubernetes cluster (kubectl cluster-info failed)." >&2
    exit 1
  fi
}

perform_preflight_checks() {
  check_dependencies helm kubectl grep sed
  check_cluster_connection
}

crd_exists() {
  local crd_name=$1
  kubectl get crd "$crd_name" >/dev/null 2>&1
}

install_or_verify_operator() {
  local operator_key=$1
  local crd_name=$2
  local release_name=$3
  local chart_name=$4
  local chart_repo_url=$5
  local chart_version=$6
  local chart_namespace=$7

  if crd_exists "$crd_name"; then
    echo "Operator '${operator_key}' already present (CRD ${crd_name}); skipping install."
    return 0
  fi

  case "$OPERATOR_MODE" in
    skip)
      echo "Operator mode is skip. Not installing '${operator_key}' (missing CRD ${crd_name})."
      return 0
      ;;
    verify)
      echo "Error: operator '${operator_key}' is missing (CRD ${crd_name})." >&2
      echo "Set --operators-mode install-missing to auto-install missing operators." >&2
      exit 1
      ;;
    install-missing)
      echo "Installing missing operator '${operator_key}' (chart ${chart_name}:${chart_version})..."
      helm upgrade --install "$release_name" "$chart_name" \
        --repo "$chart_repo_url" \
        --version "$chart_version" \
        --namespace "$chart_namespace" \
        --create-namespace \
        --wait \
        --atomic \
        --cleanup-on-fail \
        --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
      ;;
    *)
      echo "Error: unsupported operators mode '${OPERATOR_MODE}'." >&2
      exit 1
      ;;
  esac

  if ! crd_exists "$crd_name"; then
    echo "Error: operator '${operator_key}' install completed but CRD ${crd_name} is still missing." >&2
    exit 1
  fi
}

ensure_required_operators() {
  echo "Operator mode: ${OPERATOR_MODE}"

  if [[ "$OPERATOR_MODE" == "skip" ]]; then
    echo "Skipping operator checks/installs."
    return 0
  fi

  # MariaDB operator is used by PoundCake and Bakery when mariadbOperator.enabled=true.
  install_or_verify_operator \
    "mariadb-operator" \
    "mariadbs.k8s.mariadb.com" \
    "$MARIADB_OPERATOR_RELEASE_NAME" \
    "$MARIADB_OPERATOR_CHART_NAME" \
    "$MARIADB_OPERATOR_CHART_REPO_URL" \
    "$MARIADB_OPERATOR_VERSION" \
    "$MARIADB_OPERATOR_NAMESPACE"

  # Full mode uses Redis and RabbitMQ operator-backed resources for StackStorm dependencies.
  if [[ "$INSTALL_MODE" == "full" ]]; then
    install_or_verify_operator \
      "redis-operator" \
      "redis.redis.opstreelabs.in" \
      "$REDIS_OPERATOR_RELEASE_NAME" \
      "$REDIS_OPERATOR_CHART_NAME" \
      "$REDIS_OPERATOR_CHART_REPO_URL" \
      "$REDIS_OPERATOR_VERSION" \
      "$REDIS_OPERATOR_NAMESPACE"

    install_or_verify_operator \
      "rabbitmq-cluster-operator" \
      "rabbitmqclusters.rabbitmq.com" \
      "$RABBITMQ_OPERATOR_RELEASE_NAME" \
      "$RABBITMQ_OPERATOR_CHART_NAME" \
      "$RABBITMQ_OPERATOR_CHART_REPO_URL" \
      "$RABBITMQ_OPERATOR_VERSION" \
      "$RABBITMQ_OPERATOR_NAMESPACE"
  fi
}

ensure_oci_registry_auth() {
  local chart_ref=$1

  if [[ "$chart_ref" != oci://* ]]; then
    return 0
  fi

  local registry
  registry="${chart_ref#oci://}"
  registry="${registry%%/*}"

  local username="${HELM_REGISTRY_USERNAME:-${GHCR_USERNAME:-${GITHUB_ACTOR:-}}}"
  local password="${HELM_REGISTRY_PASSWORD:-${GHCR_TOKEN:-${CR_PAT:-${GITHUB_TOKEN:-}}}}"

  if [[ -n "$username" && -n "$password" ]]; then
    echo "Authenticating Helm OCI client to ${registry} as ${username}..."
    printf '%s' "$password" | helm registry login "$registry" -u "$username" --password-stdin >/dev/null
  elif [[ "$registry" == "ghcr.io" ]]; then
    echo "Note: ${chart_ref} is an OCI chart in GHCR. If it is private, export HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD (or GHCR_USERNAME/GHCR_TOKEN)." >&2
  fi
}

get_chart_version() {
  local service=$1
  local version_file=$2

  if [[ -f "$version_file" ]]; then
    grep "^[[:space:]]*${service}:" "$version_file" | sed "s/.*${service}: *//" | head -n1
  fi
}

run_helm_validation() {
  local chart_ref=$1
  local version=$2
  local namespace=$3
  local release_name=$4
  shift 4
  local render_args=("$@")
  local lint_args=()
  local template_args=()
  local skip_next=0

  for arg in "${render_args[@]}"; do
    template_args+=("$arg")

    if [[ $skip_next -eq 1 ]]; then
      skip_next=0
      continue
    fi

    if [[ "$arg" == "--post-renderer" || "$arg" == "--post-renderer-args" ]]; then
      skip_next=1
      continue
    fi

    lint_args+=("$arg")
  done

  local tmpdir
  tmpdir="$(mktemp -d)"

  helm pull "$chart_ref" --version "$version" --untar --untardir "$tmpdir"
  local chart_dir
  chart_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n1)"

  echo "Running helm lint..."
  helm lint "$chart_dir" "${lint_args[@]}"

  echo "Running helm template --debug..."
  helm template "$release_name" "$chart_ref" \
    --version "$version" \
    --namespace "$namespace" \
    "${template_args[@]}" \
    --debug >/dev/null

  rm -rf "$tmpdir"
}

rotate_chart_secrets() {
  local namespace=$1
  local release_name=$2

  local secrets=(
    "${release_name}-poundcake-admin"
    "${release_name}-poundcake-stackstorm"
    "${release_name}-stackstorm-ha-st2-apikeys"
    "st2-st2-apikeys"
    "st2-mongodb-secret"
    "st2-rabbitmq"
    "${release_name}-poundcake-mariadb-root"
    "${release_name}-poundcake-mariadb-user"
    "poundcake-st2-auth"
  )

  echo "Rotating selected chart-managed secrets (if present)..."
  for s in "${secrets[@]}"; do
    kubectl -n "$namespace" delete secret "$s" --ignore-not-found >/dev/null || true
  done
}

SERVICE_NAME="${POUNDCAKE_SERVICE_NAME:-poundcake}"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
GHCR_OWNER="${POUNDCAKE_GHCR_OWNER:-aedan}"
CHART_REPO="${POUNDCAKE_CHART_REPO:-oci://ghcr.io/${GHCR_OWNER}/charts/poundcake}"
STACKSTORM_RELEASE_NAME="${POUNDCAKE_STACKSTORM_RELEASE_NAME:-stackstorm}"
STACKSTORM_CHART_NAME="${POUNDCAKE_STACKSTORM_CHART_NAME:-stackstorm-ha}"
STACKSTORM_CHART_REPO_URL="${POUNDCAKE_STACKSTORM_CHART_REPO_URL:-https://helm.stackstorm.com/}"
STACKSTORM_VERSION_DEFAULT="${POUNDCAKE_STACKSTORM_CHART_VERSION:-1.1.0}"
OPERATOR_MODE="${POUNDCAKE_OPERATORS_MODE:-install-missing}"

MARIADB_OPERATOR_RELEASE_NAME="${POUNDCAKE_MARIADB_OPERATOR_RELEASE_NAME:-mariadb-operator}"
MARIADB_OPERATOR_NAMESPACE="${POUNDCAKE_MARIADB_OPERATOR_NAMESPACE:-mariadb-operator}"
MARIADB_OPERATOR_CHART_NAME="${POUNDCAKE_MARIADB_OPERATOR_CHART_NAME:-mariadb-operator}"
MARIADB_OPERATOR_CHART_REPO_URL="${POUNDCAKE_MARIADB_OPERATOR_CHART_REPO_URL:-https://mariadb-operator.github.io/mariadb-operator}"
MARIADB_OPERATOR_VERSION_DEFAULT="${POUNDCAKE_MARIADB_OPERATOR_CHART_VERSION:-25.10.4}"

REDIS_OPERATOR_RELEASE_NAME="${POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME:-redis-operator}"
REDIS_OPERATOR_NAMESPACE="${POUNDCAKE_REDIS_OPERATOR_NAMESPACE:-redis-operator}"
REDIS_OPERATOR_CHART_NAME="${POUNDCAKE_REDIS_OPERATOR_CHART_NAME:-redis-operator}"
REDIS_OPERATOR_CHART_REPO_URL="${POUNDCAKE_REDIS_OPERATOR_CHART_REPO_URL:-https://ot-container-kit.github.io/helm-charts/}"
REDIS_OPERATOR_VERSION_DEFAULT="${POUNDCAKE_REDIS_OPERATOR_CHART_VERSION:-0.23.0}"

RABBITMQ_OPERATOR_RELEASE_NAME="${POUNDCAKE_RABBITMQ_OPERATOR_RELEASE_NAME:-rabbitmq-cluster-operator}"
RABBITMQ_OPERATOR_NAMESPACE="${POUNDCAKE_RABBITMQ_OPERATOR_NAMESPACE:-rabbitmq-system}"
RABBITMQ_OPERATOR_CHART_NAME="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_NAME:-rabbitmq-cluster-operator}"
RABBITMQ_OPERATOR_CHART_REPO_URL="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_REPO_URL:-https://charts.bitnami.com/bitnami}"
RABBITMQ_OPERATOR_VERSION_DEFAULT="${POUNDCAKE_RABBITMQ_OPERATOR_CHART_VERSION:-4.4.34}"
APP_IMAGE_REPO="${POUNDCAKE_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake}"
UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-ui}"
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-bakery}"
INSTALL_MODE="${POUNDCAKE_INSTALL_MODE:-full}"
BAKERY_RACKSPACE_URL="${POUNDCAKE_BAKERY_RACKSPACE_URL:-}"
BAKERY_RACKSPACE_USERNAME="${POUNDCAKE_BAKERY_RACKSPACE_USERNAME:-}"
BAKERY_RACKSPACE_PASSWORD="${POUNDCAKE_BAKERY_RACKSPACE_PASSWORD:-}"
BAKERY_RACKSPACE_SECRET_NAME="${POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME:-bakery-rackspace-core}"
VERSION_FILE_PRIMARY="/etc/genestack/helm-chart-version.yaml"
VERSION_FILE_FALLBACK="/etc/genestack/helm-chart-versions.yaml"
VERSION_FILE_MANAGED="/etc/genestack/helm-chart-versions.yaml"
GLOBAL_OVERRIDES_DIR="/etc/genestack/helm-configs/global_overrides"
POUNDCAKE_CONFIG_DIR="/etc/genestack/helm-configs/poundcake"
STACKSTORM_CONFIG_DIR="/etc/genestack/helm-configs/stackstorm"
POUNDCAKE_BASE_OVERRIDES="/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml"
STACKSTORM_BASE_OVERRIDES="/opt/genestack/base-helm-configs/stackstorm/stackstorm-helm-overrides.yaml"
STACKSTORM_DEFAULT_OVERRIDES="${HELM_ROOT}/stackstorm/values-external-services.yaml"
KUSTOMIZE_RENDERER="/etc/genestack/kustomize/kustomize.sh"
KUSTOMIZE_OVERLAY_DIR="/etc/genestack/kustomize/poundcake/overlay"
KUSTOMIZE_OVERLAY_ARG="poundcake/overlay"

ROTATE_SECRETS=false
VALIDATE="${POUNDCAKE_HELM_VALIDATE:-false}"
SKIP_PREFLIGHT=false
BOOTSTRAP_DIRS=true
INTERACTIVE_BAKERY_CREDS=false
POUNDCAKE_EXTRA_ARGS=()
POST_RENDER_ARGS=()
GLOBAL_OVERRIDE_ARGS=()
POUNDCAKE_OVERRIDE_ARGS=()
STACKSTORM_OVERRIDE_ARGS=()

get_local_poundcake_chart_version() {
  local chart_file="${HELM_ROOT}/poundcake/Chart.yaml"
  if [[ -f "$chart_file" ]]; then
    grep -E "^[[:space:]]*version:" "$chart_file" | head -n1 | sed -E 's/^[[:space:]]*version:[[:space:]]*//'
  fi
}

ensure_chart_version_key() {
  local file_path=$1
  local key=$2
  local value=$3

  if grep -Eq "^[[:space:]]*${key}:" "$file_path"; then
    return 0
  fi

  local indent
  indent="$(grep -E "^[[:space:]]+[A-Za-z0-9_-]+:[[:space:]]" "$file_path" | head -n1 | sed -E 's/^([[:space:]]*).*/\1/' || true)"
  if [[ -z "${indent}" ]]; then
    indent=""
  fi

  echo "Adding missing '${key}' chart version to ${file_path}: ${value}"
  printf "\n%s%s: %s\n" "$indent" "$key" "$value" >>"$file_path"
}

apply_bakery_rackspace_secret() {
  local should_manage_secret=false

  if [[ "$INTERACTIVE_BAKERY_CREDS" == "true" ]]; then
    should_manage_secret=true

    local prompt_url_default="${BAKERY_RACKSPACE_URL:-https://ws.core.rackspace.com}"
    local prompt_user_default="${BAKERY_RACKSPACE_USERNAME:-}"

    read -r -p "Bakery Rackspace Core URL [${prompt_url_default}]: " prompt_url
    BAKERY_RACKSPACE_URL="${prompt_url:-$prompt_url_default}"

    read -r -p "Bakery Rackspace Core username [${prompt_user_default}]: " prompt_user
    BAKERY_RACKSPACE_USERNAME="${prompt_user:-$prompt_user_default}"

    read -r -s -p "Bakery Rackspace Core password: " prompt_password
    echo
    BAKERY_RACKSPACE_PASSWORD="$prompt_password"
  fi

  if [[ -n "${BAKERY_RACKSPACE_URL}${BAKERY_RACKSPACE_USERNAME}${BAKERY_RACKSPACE_PASSWORD}" ]]; then
    should_manage_secret=true
  fi

  if [[ "$should_manage_secret" != "true" ]]; then
    return 0
  fi

  if [[ -z "$BAKERY_RACKSPACE_URL" || -z "$BAKERY_RACKSPACE_USERNAME" || -z "$BAKERY_RACKSPACE_PASSWORD" ]]; then
    echo "Error: Bakery Rackspace Core credentials require url, username, and password." >&2
    echo "Use --interactive-bakery-creds or provide all of:" >&2
    echo "  --bakery-rackspace-url --bakery-rackspace-username --bakery-rackspace-password" >&2
    exit 1
  fi

  if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "Creating namespace '${NAMESPACE}' to store Bakery credential secret..."
    kubectl create namespace "$NAMESPACE" >/dev/null
  fi

  echo "Applying Bakery Rackspace Core secret '${BAKERY_RACKSPACE_SECRET_NAME}' in namespace '${NAMESPACE}'..."
  kubectl -n "$NAMESPACE" create secret generic "$BAKERY_RACKSPACE_SECRET_NAME" \
    --from-literal=rackspace-core-url="$BAKERY_RACKSPACE_URL" \
    --from-literal=rackspace-core-username="$BAKERY_RACKSPACE_USERNAME" \
    --from-literal=rackspace-core-password="$BAKERY_RACKSPACE_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -

  # Ensure Bakery is enabled and wired to the managed secret in any install mode.
  POUNDCAKE_OVERRIDE_ARGS+=("--set" "bakery.enabled=true")
  POUNDCAKE_OVERRIDE_ARGS+=("--set" "bakery.rackspaceCore.existingSecret=${BAKERY_RACKSPACE_SECRET_NAME}")
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      INSTALL_MODE="$2"
      shift 2
      ;;
    --rotate-secrets)
      ROTATE_SECRETS=true
      shift
      ;;
    --validate)
      VALIDATE=true
      shift
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=true
      shift
      ;;
    --skip-bootstrap-dirs)
      BOOTSTRAP_DIRS=false
      shift
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
    --interactive-bakery-creds|--interactive-bakery-credentials)
      INTERACTIVE_BAKERY_CREDS=true
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
      POUNDCAKE_EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "$INSTALL_MODE" != "full" && "$INSTALL_MODE" != "bakery-only" ]]; then
  echo "Error: invalid mode '$INSTALL_MODE'. Valid values: full, bakery-only" >&2
  exit 1
fi

if [[ "$OPERATOR_MODE" != "install-missing" && "$OPERATOR_MODE" != "verify" && "$OPERATOR_MODE" != "skip" ]]; then
  echo "Error: invalid operators mode '$OPERATOR_MODE'. Valid values: install-missing, verify, skip" >&2
  exit 1
fi

if [[ "$SKIP_PREFLIGHT" != "true" ]]; then
  perform_preflight_checks
fi

if [[ "$BOOTSTRAP_DIRS" == "true" ]]; then
  for dir_path in "$GLOBAL_OVERRIDES_DIR" "$POUNDCAKE_CONFIG_DIR" "$STACKSTORM_CONFIG_DIR"; do
    if [[ -d "$dir_path" ]]; then
      echo "Bootstrap: ${dir_path} already exists, skipping."
    else
      echo "Bootstrap: creating ${dir_path}"
      mkdir -p "$dir_path"
    fi
  done
fi

if [[ ! -f "$VERSION_FILE_MANAGED" ]]; then
  if [[ -f "$VERSION_FILE_PRIMARY" ]]; then
    cp "$VERSION_FILE_PRIMARY" "$VERSION_FILE_MANAGED"
  else
    touch "$VERSION_FILE_MANAGED"
  fi
fi

POUNDCAKE_VERSION="$(get_chart_version "poundcake" "$VERSION_FILE_MANAGED" || true)"
STACKSTORM_VERSION="$(get_chart_version "stackstorm" "$VERSION_FILE_MANAGED" || true)"
MARIADB_OPERATOR_VERSION="$(get_chart_version "mariadb-operator" "$VERSION_FILE_MANAGED" || true)"
REDIS_OPERATOR_VERSION="$(get_chart_version "redis-operator" "$VERSION_FILE_MANAGED" || true)"
RABBITMQ_OPERATOR_VERSION="$(get_chart_version "rabbitmq-cluster-operator" "$VERSION_FILE_MANAGED" || true)"

LOCAL_POUNDCAKE_VERSION="$(get_local_poundcake_chart_version || true)"
POUNDCAKE_VERSION="${POUNDCAKE_VERSION:-${POUNDCAKE_CHART_VERSION:-$LOCAL_POUNDCAKE_VERSION}}"
STACKSTORM_VERSION="${STACKSTORM_VERSION:-$STACKSTORM_VERSION_DEFAULT}"
MARIADB_OPERATOR_VERSION="${MARIADB_OPERATOR_VERSION:-$MARIADB_OPERATOR_VERSION_DEFAULT}"
REDIS_OPERATOR_VERSION="${REDIS_OPERATOR_VERSION:-$REDIS_OPERATOR_VERSION_DEFAULT}"
RABBITMQ_OPERATOR_VERSION="${RABBITMQ_OPERATOR_VERSION:-$RABBITMQ_OPERATOR_VERSION_DEFAULT}"

if [[ -z "${POUNDCAKE_VERSION}" ]]; then
  echo "Error: could not determine PoundCake chart version. Set /etc/genestack/helm-chart-versions.yaml key 'poundcake' or env POUNDCAKE_CHART_VERSION." >&2
  exit 1
fi

ensure_chart_version_key "$VERSION_FILE_MANAGED" "poundcake" "$POUNDCAKE_VERSION"
ensure_chart_version_key "$VERSION_FILE_MANAGED" "stackstorm" "$STACKSTORM_VERSION"
ensure_chart_version_key "$VERSION_FILE_MANAGED" "mariadb-operator" "$MARIADB_OPERATOR_VERSION"
ensure_chart_version_key "$VERSION_FILE_MANAGED" "redis-operator" "$REDIS_OPERATOR_VERSION"
ensure_chart_version_key "$VERSION_FILE_MANAGED" "rabbitmq-cluster-operator" "$RABBITMQ_OPERATOR_VERSION"

ensure_required_operators

STACKSTORM_API_URL="http://${STACKSTORM_RELEASE_NAME}-st2api.${NAMESPACE}.svc.cluster.local:9101"
STACKSTORM_AUTH_URL="http://${STACKSTORM_RELEASE_NAME}-st2auth.${NAMESPACE}.svc.cluster.local:9100"

echo "Installing PoundCake chart version: ${POUNDCAKE_VERSION}"
echo "Installing StackStorm chart version: ${STACKSTORM_VERSION}"
ensure_oci_registry_auth "$CHART_REPO"

if [[ -f "$POUNDCAKE_BASE_OVERRIDES" ]]; then
  POUNDCAKE_OVERRIDE_ARGS+=("-f" "$POUNDCAKE_BASE_OVERRIDES")
fi

if [[ -d "$GLOBAL_OVERRIDES_DIR" ]] && compgen -G "${GLOBAL_OVERRIDES_DIR}/*.yaml" >/dev/null; then
  for yaml_file in "${GLOBAL_OVERRIDES_DIR}"/*.yaml; do
    GLOBAL_OVERRIDE_ARGS+=("-f" "$yaml_file")
  done
fi

POUNDCAKE_OVERRIDE_ARGS+=("${GLOBAL_OVERRIDE_ARGS[@]}")

if [[ -d "$POUNDCAKE_CONFIG_DIR" ]] && compgen -G "${POUNDCAKE_CONFIG_DIR}/*.yaml" >/dev/null; then
  for yaml_file in "${POUNDCAKE_CONFIG_DIR}"/*.yaml; do
    POUNDCAKE_OVERRIDE_ARGS+=("-f" "$yaml_file")
  done
fi

if [[ -f "$STACKSTORM_BASE_OVERRIDES" ]]; then
  STACKSTORM_OVERRIDE_ARGS+=("-f" "$STACKSTORM_BASE_OVERRIDES")
fi
if [[ -f "$STACKSTORM_DEFAULT_OVERRIDES" ]]; then
  STACKSTORM_OVERRIDE_ARGS+=("-f" "$STACKSTORM_DEFAULT_OVERRIDES")
fi
STACKSTORM_OVERRIDE_ARGS+=("${GLOBAL_OVERRIDE_ARGS[@]}")

if [[ -d "$STACKSTORM_CONFIG_DIR" ]] && compgen -G "${STACKSTORM_CONFIG_DIR}/*.yaml" >/dev/null; then
  for yaml_file in "${STACKSTORM_CONFIG_DIR}"/*.yaml; do
    STACKSTORM_OVERRIDE_ARGS+=("-f" "$yaml_file")
  done
fi

apply_bakery_rackspace_secret

# Add post-renderer if available AND overlay exists.
if [[ "$INSTALL_MODE" != "bakery-only" && -f "$KUSTOMIZE_RENDERER" && -d "$KUSTOMIZE_OVERLAY_DIR" ]]; then
  POST_RENDER_ARGS+=("--post-renderer" "$KUSTOMIZE_RENDERER")
  POST_RENDER_ARGS+=("--post-renderer-args" "$KUSTOMIZE_OVERLAY_ARG")
fi

if [[ "$ROTATE_SECRETS" == "true" ]]; then
  rotate_chart_secrets "$NAMESPACE" "$RELEASE_NAME"
fi

if [[ "$VALIDATE" == "true" ]]; then
  run_helm_validation "$CHART_REPO" "$POUNDCAKE_VERSION" "$NAMESPACE" "$RELEASE_NAME" \
    --set "deployment.mode=${INSTALL_MODE}" \
    --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}" \
    --set "stackstorm.url=${STACKSTORM_API_URL}" \
    --set "stackstorm.authUrl=${STACKSTORM_AUTH_URL}" \
    "${POUNDCAKE_OVERRIDE_ARGS[@]}" \
    "${POST_RENDER_ARGS[@]}" \
    "${POUNDCAKE_EXTRA_ARGS[@]}"
fi

POUNDCAKE_PHASE1_CMD=(
  helm upgrade --install "$RELEASE_NAME" "$CHART_REPO"
  --version "$POUNDCAKE_VERSION"
  --namespace "$NAMESPACE"
  --create-namespace
  --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
  --set "bootstrap.poundcakeBootstrap.enabled=false"
  --set "deployment.mode=full"
  --set "image.repository=${APP_IMAGE_REPO}"
  --set "image.tag=${POUNDCAKE_VERSION}"
  --set "ui.image.repository=${UI_IMAGE_REPO}"
  --set "ui.image.tag=${POUNDCAKE_VERSION}"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "bakery.image.tag=${POUNDCAKE_VERSION}"
  --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}"
  --set "stackstorm.url=${STACKSTORM_API_URL}"
  --set "stackstorm.authUrl=${STACKSTORM_AUTH_URL}"
  "${POUNDCAKE_OVERRIDE_ARGS[@]}"
  "${POST_RENDER_ARGS[@]}"
)

STACKSTORM_CMD=(
  helm upgrade --install "$STACKSTORM_RELEASE_NAME" "$STACKSTORM_CHART_NAME"
  --repo "$STACKSTORM_CHART_REPO_URL"
  --version "$STACKSTORM_VERSION"
  --namespace "$NAMESPACE"
  --create-namespace
  --wait
  --atomic
  --cleanup-on-fail
  --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
  "${STACKSTORM_OVERRIDE_ARGS[@]}"
)

POUNDCAKE_PHASE3_CMD=(
  helm upgrade --install "$RELEASE_NAME" "$CHART_REPO"
  --version "$POUNDCAKE_VERSION"
  --namespace "$NAMESPACE"
  --create-namespace
  --wait
  --atomic
  --cleanup-on-fail
  --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
  --set "bootstrap.poundcakeBootstrap.enabled=true"
  --set "deployment.mode=full"
  --set "image.repository=${APP_IMAGE_REPO}"
  --set "image.tag=${POUNDCAKE_VERSION}"
  --set "ui.image.repository=${UI_IMAGE_REPO}"
  --set "ui.image.tag=${POUNDCAKE_VERSION}"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "bakery.image.tag=${POUNDCAKE_VERSION}"
  --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}"
  --set "stackstorm.url=${STACKSTORM_API_URL}"
  --set "stackstorm.authUrl=${STACKSTORM_AUTH_URL}"
  "${POUNDCAKE_OVERRIDE_ARGS[@]}"
  "${POST_RENDER_ARGS[@]}"
)

BAKERY_ONLY_CMD=(
  helm upgrade --install "$RELEASE_NAME" "$CHART_REPO"
  --version "$POUNDCAKE_VERSION"
  --namespace "$NAMESPACE"
  --create-namespace
  --wait
  --atomic
  --cleanup-on-fail
  --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
  --set "deployment.mode=bakery-only"
  --set "bakery.enabled=true"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "bakery.image.tag=${POUNDCAKE_VERSION}"
  "${POUNDCAKE_OVERRIDE_ARGS[@]}"
  "${POUNDCAKE_EXTRA_ARGS[@]}"
)

if [[ "$INSTALL_MODE" == "bakery-only" ]]; then
  echo "Mode: bakery-only"
  printf '%q ' "${BAKERY_ONLY_CMD[@]}"
  echo
  "${BAKERY_ONLY_CMD[@]}"
  exit 0
fi

echo "Phase 1/3: Install PoundCake prerequisites (external StackStorm mode)"
printf '%q ' "${POUNDCAKE_PHASE1_CMD[@]}" "${POUNDCAKE_EXTRA_ARGS[@]}"
echo
"${POUNDCAKE_PHASE1_CMD[@]}" "${POUNDCAKE_EXTRA_ARGS[@]}"

echo "Phase 2/3: Install StackStorm as separate release"
printf '%q ' "${STACKSTORM_CMD[@]}"
echo
"${STACKSTORM_CMD[@]}"

echo "Phase 3/3: Reconcile PoundCake after StackStorm is ready"
printf '%q ' "${POUNDCAKE_PHASE3_CMD[@]}" "${POUNDCAKE_EXTRA_ARGS[@]}"
echo
"${POUNDCAKE_PHASE3_CMD[@]}" "${POUNDCAKE_EXTRA_ARGS[@]}"

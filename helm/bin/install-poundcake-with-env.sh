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
POUNDCAKE_IMAGE_TAG="${POUNDCAKE_IMAGE_TAG:-d5dbf49}"
STACKSTORM_IMAGE_REPO="${POUNDCAKE_STACKSTORM_IMAGE_REPO:-stackstorm/st2}"
STACKSTORM_IMAGE_TAG="${POUNDCAKE_STACKSTORM_IMAGE_TAG:-3.9.0}"
UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-}"
UI_IMAGE_TAG="${POUNDCAKE_UI_IMAGE_TAG:-}"
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-}"
CHART_VERSION="${POUNDCAKE_CHART_VERSION:-}"
VERSION_FILE="${POUNDCAKE_VERSION_FILE:-}"
HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-}"
HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-}"
IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"

BASE_OVERRIDES="${POUNDCAKE_BASE_OVERRIDES:-/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml}"
GLOBAL_OVERRIDES_DIR="${POUNDCAKE_GLOBAL_OVERRIDES_DIR:-/etc/genestack/helm-configs/global_overrides}"
SERVICE_CONFIG_DIR="${POUNDCAKE_SERVICE_CONFIG_DIR:-/etc/genestack/helm-configs/poundcake}"
POST_RENDERER="${POUNDCAKE_HELM_POST_RENDERER:-/etc/genestack/kustomize/kustomize.sh}"
POST_RENDERER_ARGS="${POUNDCAKE_HELM_POST_RENDERER_ARGS:-poundcake/overlay}"
POST_RENDERER_OVERLAY_DIR="${POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR:-/etc/genestack/kustomize/poundcake/overlay}"

VALIDATE="${POUNDCAKE_HELM_VALIDATE:-false}"
SKIP_PREFLIGHT="false"
ROTATE_SECRETS="false"
EXTRA_ARGS=()

usage() {
  cat <<'USAGE_EOF'
Usage:
  install-poundcake.sh [installer options] [helm upgrade/install args]

Installer options:
  --validate        Run helm lint + helm template --debug before install
  --skip-preflight  Skip dependency/cluster preflight checks
  --rotate-secrets  Delete known chart-managed secrets before install

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
  POUNDCAKE_HELM_VALIDATE          (default: false; same as --validate)
  POUNDCAKE_IMAGE_REPO             (default: ghcr.io/${POUNDCAKE_GHCR_OWNER}/poundcake)
  POUNDCAKE_IMAGE_TAG              (default: d5dbf49)
  POUNDCAKE_UI_IMAGE_REPO          (optional; sets uiImage.repository)
  POUNDCAKE_UI_IMAGE_TAG           (optional; sets uiImage.tag)
  POUNDCAKE_BAKERY_IMAGE_REPO      (optional; accepted for compatibility)
  HELM_REGISTRY_USERNAME           (optional; for OCI login)
  HELM_REGISTRY_PASSWORD           (optional; for OCI login)
  POUNDCAKE_IMAGE_PULL_SECRET_NAME     (default: ghcr-pull)
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET   (default: true)
  POUNDCAKE_IMAGE_PULL_SECRET_EMAIL    (default: noreply@local)
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED  (default: true)
  POUNDCAKE_RELEASE_NAME           (default: poundcake)
  POUNDCAKE_NAMESPACE              (default: rackspace)
  POUNDCAKE_HELM_TIMEOUT           (default: 120m)
  POUNDCAKE_HELM_WAIT              (default: false)
  POUNDCAKE_ALLOW_HOOK_WAIT        (default: false; required when forcing --wait/--atomic)
  POUNDCAKE_HELM_ATOMIC            (default: false)
  POUNDCAKE_HELM_CLEANUP_ON_FAIL   (default: false)

Examples:
  ./install/install-helm.sh
  ./install/install-helm.sh --validate
  ./install/install-helm.sh --skip-preflight -f /path/to/values.yaml
USAGE_EOF
}

check_dependencies() {
  local missing=0
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: required command '$cmd' not found in PATH." >&2
      missing=1
    fi
  done
  if [[ "$missing" -eq 1 ]]; then
    exit 1
  fi
}

check_cluster_connection() {
  if ! kubectl cluster-info >/dev/null 2>&1; then
    echo "Error: cannot connect to Kubernetes cluster (kubectl cluster-info failed)." >&2
    exit 1
  fi
}

perform_preflight_checks() {
  check_dependencies helm kubectl grep sed awk find sort
  check_cluster_connection
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
    echo "Authenticating Helm OCI client to ${registry_host} as ${username}..."
    printf '%s' "${password}" | helm registry login "${registry_host}" -u "${username}" --password-stdin >/dev/null
  else
    echo "Note: ${chart_source} is OCI-based. Set HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD for private charts." >&2
  fi
}

collect_yaml_files() {
  local directory="$1"
  if [[ -d "${directory}" ]]; then
    find "${directory}" -maxdepth 1 -type f -name '*.yaml' | LC_ALL=C sort
  fi
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

    CHART_VERSION="$(get_chart_version_from_file "${candidate}" "poundcake")"
    if [[ -z "${CHART_VERSION}" ]]; then
      CHART_VERSION="$(grep -E '^[[:space:]]*poundcake:[[:space:]]*' "${candidate}" | sed -E 's/^[[:space:]]*poundcake:[[:space:]]*//' | head -n1)"
    fi

    if [[ -n "${CHART_VERSION}" ]]; then
      return
    fi
  done
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
    if [[ "${arg}" == "--post-renderer" || "${arg}" == "--post-renderer-args" ]]; then
      ((i+=2))
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

  echo "Running helm lint..."
  helm lint "${lint_chart_source}" "${lint_args[@]}"

  echo "Running helm template --debug..."
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

  echo "Rotating selected chart-managed secrets (if present)..."
  local s
  for s in "${secrets[@]}"; do
    kubectl -n "${namespace}" delete secret "${s}" --ignore-not-found >/dev/null || true
  done
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --validate)
      VALIDATE="true"
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
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "${SKIP_PREFLIGHT}" != "true" ]]; then
  perform_preflight_checks
fi

if [[ "${CREATE_IMAGE_PULL_SECRET}" == "true" ]] && ! command -v kubectl >/dev/null 2>&1; then
  echo "Error: kubectl is required when POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true." >&2
  exit 1
fi

if [[ -z "${CHART_REPO}" ]]; then
  CHART_SOURCE="${CHART_DIR}"
else
  CHART_SOURCE="${CHART_REPO}"
fi

resolve_chart_version
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
  echo "Error: startup jobs are Helm post-install/post-upgrade hooks and workload init containers are marker-gated." >&2
  echo "Using --wait/--atomic can deadlock before hook jobs run, so jobs may never be created." >&2
  echo "Re-run with POUNDCAKE_HELM_WAIT=false (recommended)." >&2
  echo "If you intentionally want wait semantics, set POUNDCAKE_ALLOW_HOOK_WAIT=true." >&2
  exit 1
fi

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" && -z "${IMAGE_PULL_SECRET_NAME}" ]]; then
  echo "Error: POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true requires POUNDCAKE_IMAGE_PULL_SECRET_NAME." >&2
  exit 1
fi

if [[ "${CREATE_IMAGE_PULL_SECRET}" == "true" ]]; then
  if [[ -z "${HELM_REGISTRY_USERNAME}" || -z "${HELM_REGISTRY_PASSWORD}" ]]; then
    echo "Error: POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true requires HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD." >&2
    exit 1
  fi
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    echo "Namespace '${NAMESPACE}' does not exist; creating it for image pull secret setup..."
    kubectl create namespace "${NAMESPACE}"
  fi
  echo "Creating/updating image pull secret '${IMAGE_PULL_SECRET_NAME}' in namespace '${NAMESPACE}'..."
  kubectl -n "${NAMESPACE}" create secret docker-registry "${IMAGE_PULL_SECRET_NAME}" \
    --docker-server=ghcr.io \
    --docker-username="${HELM_REGISTRY_USERNAME}" \
    --docker-password="${HELM_REGISTRY_PASSWORD}" \
    --docker-email="${IMAGE_PULL_SECRET_EMAIL}" \
    --dry-run=client -o yaml | kubectl apply -f -
else
  echo "Skipping image pull secret creation (POUNDCAKE_CREATE_IMAGE_PULL_SECRET=${CREATE_IMAGE_PULL_SECRET})."
fi

if [[ "${ROTATE_SECRETS}" == "true" ]]; then
  rotate_chart_secrets "${NAMESPACE}" "${RELEASE_NAME}"
fi

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

POST_RENDER_ARGS=()
if [[ -f "${POST_RENDERER}" && -d "${POST_RENDERER_OVERLAY_DIR}" ]]; then
  POST_RENDER_ARGS+=("--post-renderer" "${POST_RENDERER}")
  if [[ -n "${POST_RENDERER_ARGS}" ]]; then
    POST_RENDER_ARGS+=("--post-renderer-args" "${POST_RENDERER_ARGS}")
  fi
fi

INSTALLER_SET_ARGS=(
  --set "poundcakeImage.repository=${POUNDCAKE_IMAGE_REPO}"
  --set "poundcakeImage.tag=${POUNDCAKE_IMAGE_TAG}"
  --set "stackstormImage.repository=${STACKSTORM_IMAGE_REPO}"
  --set "stackstormImage.tag=${STACKSTORM_IMAGE_TAG}"
)

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  INSTALLER_SET_ARGS+=(--set "poundcakeImage.pullSecrets[0]=${IMAGE_PULL_SECRET_NAME}")
fi

if [[ -n "${UI_IMAGE_REPO}" ]]; then
  INSTALLER_SET_ARGS+=(--set "uiImage.repository=${UI_IMAGE_REPO}")
fi
if [[ -n "${UI_IMAGE_TAG}" ]]; then
  INSTALLER_SET_ARGS+=(--set "uiImage.tag=${UI_IMAGE_TAG}")
fi
if [[ -n "${BAKERY_IMAGE_REPO}" ]]; then
  INSTALLER_SET_ARGS+=(--set "bakery.image.repository=${BAKERY_IMAGE_REPO}")
fi

COMMON_HELM_ARGS=(
  --namespace "${NAMESPACE}"
  --timeout "${HELM_TIMEOUT}"
  "${OVERRIDE_ARGS[@]}"
  "${POST_RENDER_ARGS[@]}"
  "${INSTALLER_SET_ARGS[@]}"
)

if [[ -n "${CHART_VERSION}" ]]; then
  COMMON_HELM_ARGS+=(--version "${CHART_VERSION}")
fi

if [[ "${VALIDATE}" == "true" ]]; then
  run_helm_validation "${CHART_SOURCE}" "${NAMESPACE}" "${RELEASE_NAME}" \
    "${COMMON_HELM_ARGS[@]}" \
    "${EXTRA_ARGS[@]}"
fi

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

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  TEMPLATE_ARGS=()
  for arg in "${EXTRA_ARGS[@]}"; do
    case "${arg}" in
      --wait|--atomic|--cleanup-on-fail|--create-namespace)
        continue
        ;;
    esac
    TEMPLATE_ARGS+=("${arg}")
  done

  RENDERED_MANIFEST="$(mktemp)"
  HELM_TEMPLATE_CMD=(
    helm template "${RELEASE_NAME}" "${CHART_SOURCE}"
    "${COMMON_HELM_ARGS[@]}"
  )

  "${HELM_TEMPLATE_CMD[@]}" \
    "${TEMPLATE_ARGS[@]}" \
    > "${RENDERED_MANIFEST}"

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
    rm -f "${RENDERED_MANIFEST}"
    echo "Error: rendered PoundCake manifests do not include imagePullSecrets '${IMAGE_PULL_SECRET_NAME}'." >&2
    echo "Refusing install to avoid anonymous private-registry pulls." >&2
    exit 1
  fi
  rm -f "${RENDERED_MANIFEST}"
fi

echo "Installing PoundCake release: ${RELEASE_NAME}"
echo "Namespace: ${NAMESPACE}"
echo "Chart source: ${CHART_SOURCE}"
if [[ "${CHART_SOURCE}" == oci://* ]]; then
  echo "Chart version: ${CHART_VERSION:-"(not set)"}"
fi
echo "PoundCake image: ${POUNDCAKE_IMAGE_REPO}:${POUNDCAKE_IMAGE_TAG}"
if [[ -n "${UI_IMAGE_REPO}" ]]; then
  echo "UI image repo override: ${UI_IMAGE_REPO}"
fi
if [[ -n "${UI_IMAGE_TAG}" ]]; then
  echo "UI image tag override: ${UI_IMAGE_TAG}"
fi
if [[ -n "${BAKERY_IMAGE_REPO}" ]]; then
  echo "Bakery image repo override: ${BAKERY_IMAGE_REPO}"
fi
if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  echo "Image pull secret injection: enabled (${IMAGE_PULL_SECRET_NAME})"
  echo "Image pull secret key: poundcakeImage.pullSecrets"
else
  echo "Image pull secret injection: disabled (POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=${IMAGE_PULL_SECRET_ENABLED})"
fi

echo "Executing Helm command:"
printf '%q ' "${HELM_CMD[@]}" "${EXTRA_ARGS[@]}"
echo

"${HELM_CMD[@]}" "${EXTRA_ARGS[@]}"

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
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-}"
CHART_VERSION="${POUNDCAKE_CHART_VERSION:-}"
VERSION_FILE="${POUNDCAKE_VERSION_FILE:-/etc/genestack/helm-chart-versions.yaml}"
HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-}"
HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-}"
IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"

EXTRA_ARGS=("$@")

usage() {
  cat <<'EOF'
Usage:
  install-poundcake.sh [helm upgrade/install args]

Environment overrides:
  POUNDCAKE_GHCR_OWNER             (default: rackerlabs)
  POUNDCAKE_CHART_REPO             (default: local chart at ./helm)
  POUNDCAKE_CHART_VERSION          (optional; for OCI repo installs)
  POUNDCAKE_IMAGE_REPO             (default: ghcr.io/${POUNDCAKE_GHCR_OWNER}/poundcake)
  POUNDCAKE_IMAGE_TAG              (default: d5dbf49)
  POUNDCAKE_UI_IMAGE_REPO          (optional; accepted for compatibility)
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
  POUNDCAKE_GHCR_OWNER=rackerchris ./install/install-helm.sh
  POUNDCAKE_CHART_REPO=oci://ghcr.io/rackerchris/charts/poundcake-standalone ./install/install-helm.sh
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "Error: helm is not installed or not in PATH." >&2
  exit 1
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
  ' "${version_file}"
}

if [[ -z "${CHART_VERSION}" && -f "${VERSION_FILE}" ]]; then
  detected_version="$(get_chart_version_from_file "${VERSION_FILE}" "poundcake")"
  if [[ -n "${detected_version}" ]]; then
    CHART_VERSION="${detected_version}"
  fi
fi

if [[ "${CHART_SOURCE}" == oci://* && -n "${HELM_REGISTRY_USERNAME}" ]]; then
  registry_host="$(echo "${CHART_SOURCE}" | sed -E 's#^oci://([^/]+)/.*#\1#')"
  if [[ -n "${HELM_REGISTRY_PASSWORD}" ]]; then
    echo "Authenticating Helm OCI client to ${registry_host} as ${HELM_REGISTRY_USERNAME}..."
    helm registry login "${registry_host}" -u "${HELM_REGISTRY_USERNAME}" --password-stdin <<<"${HELM_REGISTRY_PASSWORD}"
  else
    echo "HELM_REGISTRY_USERNAME is set but HELM_REGISTRY_PASSWORD is empty; skipping registry login."
  fi
fi

wait_requested=false
if [[ "${HELM_WAIT}" == "true" || "${HELM_ATOMIC}" == "true" ]]; then
  wait_requested=true
fi
if (( ${#EXTRA_ARGS[@]} )); then
  for arg in "${EXTRA_ARGS[@]}"; do
    if [[ "${arg}" == "--wait" || "${arg}" == "--atomic" ]]; then
      wait_requested=true
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

HELM_CMD=(
  helm upgrade --install "${RELEASE_NAME}" "${CHART_SOURCE}"
  --namespace "${NAMESPACE}"
  --create-namespace
  --timeout "${HELM_TIMEOUT}"
  --set "poundcakeImage.repository=${POUNDCAKE_IMAGE_REPO}"
  --set "poundcakeImage.tag=${POUNDCAKE_IMAGE_TAG}"
  --set "stackstormImage.repository=${STACKSTORM_IMAGE_REPO}"
  --set "stackstormImage.tag=${STACKSTORM_IMAGE_TAG}"
)

if [[ "${IMAGE_PULL_SECRET_ENABLED}" == "true" ]]; then
  HELM_CMD+=(--set "poundcakeImage.pullSecrets[0]=${IMAGE_PULL_SECRET_NAME}")
fi

# Keep compatibility with legacy caller env/overrides even if chart doesn't consume all keys yet.
if [[ -n "${UI_IMAGE_REPO}" ]]; then
  HELM_CMD+=(--set "ui.image.repository=${UI_IMAGE_REPO}")
fi
if [[ -n "${BAKERY_IMAGE_REPO}" ]]; then
  HELM_CMD+=(--set "bakery.image.repository=${BAKERY_IMAGE_REPO}")
fi

if [[ "${CHART_SOURCE}" == oci://* && -n "${CHART_VERSION}" ]]; then
  HELM_CMD+=(--version "${CHART_VERSION}")
fi

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
    --namespace "${NAMESPACE}"
    --timeout "${HELM_TIMEOUT}"
    --set "poundcakeImage.repository=${POUNDCAKE_IMAGE_REPO}"
    --set "poundcakeImage.tag=${POUNDCAKE_IMAGE_TAG}"
    --set "stackstormImage.repository=${STACKSTORM_IMAGE_REPO}"
    --set "stackstormImage.tag=${STACKSTORM_IMAGE_TAG}"
    --set "poundcakeImage.pullSecrets[0]=${IMAGE_PULL_SECRET_NAME}"
  )
  if [[ "${CHART_SOURCE}" == oci://* && -n "${CHART_VERSION}" ]]; then
    HELM_TEMPLATE_CMD+=(--version "${CHART_VERSION}")
  fi
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

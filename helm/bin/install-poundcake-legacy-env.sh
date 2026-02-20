#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
DEFAULT_LOCAL_CHART="${PROJECT_ROOT}/helm/poundcake"

FORK_OWNER="${FORK_OWNER:-rackerlabs}"
GHCR_OWNER="${POUNDCAKE_GHCR_OWNER:-$FORK_OWNER}"

RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
HELM_TIMEOUT="${POUNDCAKE_HELM_TIMEOUT:-120m}"
HELM_WAIT="${POUNDCAKE_HELM_WAIT:-false}"
HELM_ATOMIC="${POUNDCAKE_HELM_ATOMIC:-false}"
HELM_CLEANUP_ON_FAIL="${POUNDCAKE_HELM_CLEANUP_ON_FAIL:-false}"

CHART_REPO="${POUNDCAKE_CHART_REPO:-}"
CHART_VERSION="${POUNDCAKE_CHART_VERSION:-}"
VERSION_FILE="${POUNDCAKE_VERSION_FILE:-/etc/genestack/helm-chart-versions.yaml}"

HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-$FORK_OWNER}"
HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-}"
IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"

POUNDCAKE_IMAGE_REPO="${POUNDCAKE_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake}"
POUNDCAKE_IMAGE_TAG="${POUNDCAKE_IMAGE_TAG:-latest}"
UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-ui}"
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-bakery}"
STACKSTORM_IMAGE_REPO="${POUNDCAKE_STACKSTORM_IMAGE_REPO:-stackstorm/st2}"
STACKSTORM_IMAGE_TAG="${POUNDCAKE_STACKSTORM_IMAGE_TAG:-3.9.0}"

EXTRA_ARGS=("$@")

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [helm upgrade/install args]

Environment overrides:
  FORK_OWNER
  HELM_REGISTRY_USERNAME
  HELM_REGISTRY_PASSWORD
  POUNDCAKE_IMAGE_PULL_SECRET_NAME
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET
  POUNDCAKE_IMAGE_PULL_SECRET_EMAIL
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED
  POUNDCAKE_CHART_REPO
  POUNDCAKE_CHART_VERSION
  POUNDCAKE_VERSION_FILE
  POUNDCAKE_GHCR_OWNER
  POUNDCAKE_IMAGE_REPO
  POUNDCAKE_IMAGE_TAG
  POUNDCAKE_UI_IMAGE_REPO
  POUNDCAKE_BAKERY_IMAGE_REPO
  POUNDCAKE_STACKSTORM_IMAGE_REPO
  POUNDCAKE_STACKSTORM_IMAGE_TAG
  POUNDCAKE_RELEASE_NAME
  POUNDCAKE_NAMESPACE
  POUNDCAKE_HELM_TIMEOUT
  POUNDCAKE_HELM_WAIT
  POUNDCAKE_HELM_ATOMIC
  POUNDCAKE_HELM_CLEANUP_ON_FAIL

Examples:
  source ${PROJECT_ROOT}/install/set-env-helper.sh
  ${SCRIPT_DIR}/$(basename "$0")
  ${SCRIPT_DIR}/$(basename "$0") -f /path/to/values.yaml
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

check_dependencies() {
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: required command '$cmd' not found in PATH." >&2
      exit 1
    fi
  done
}

check_dependencies helm

get_chart_version() {
  local service=$1
  local version_file=$2
  if [[ -f "$version_file" ]]; then
    grep "^[[:space:]]*${service}:" "$version_file" | sed "s/.*${service}: *//" | head -n1
  fi
}

if [[ -z "$CHART_REPO" ]]; then
  CHART_SOURCE="$DEFAULT_LOCAL_CHART"
else
  CHART_SOURCE="$CHART_REPO"
fi

if [[ ! -e "$CHART_SOURCE" && "$CHART_SOURCE" != oci://* ]]; then
  echo "Error: chart source '${CHART_SOURCE}' does not exist." >&2
  exit 1
fi

if [[ -z "$CHART_VERSION" ]]; then
  CHART_VERSION="$(get_chart_version "poundcake" "$VERSION_FILE" || true)"
fi

ensure_oci_registry_auth() {
  local chart_ref=$1

  if [[ "$chart_ref" != oci://* ]]; then
    return 0
  fi

  local registry
  registry="${chart_ref#oci://}"
  registry="${registry%%/*}"

  if [[ -n "$HELM_REGISTRY_USERNAME" && -n "$HELM_REGISTRY_PASSWORD" ]]; then
    echo "Authenticating Helm OCI client to ${registry} as ${HELM_REGISTRY_USERNAME}..."
    printf '%s' "$HELM_REGISTRY_PASSWORD" | helm registry login "$registry" -u "$HELM_REGISTRY_USERNAME" --password-stdin >/dev/null
  elif [[ "$registry" == "ghcr.io" ]]; then
    echo "Note: ${chart_ref} is an OCI chart in GHCR. Set HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD for private repositories." >&2
  fi
}

if [[ "$IMAGE_PULL_SECRET_ENABLED" == "true" && -z "$IMAGE_PULL_SECRET_NAME" ]]; then
  echo "Error: POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true requires POUNDCAKE_IMAGE_PULL_SECRET_NAME." >&2
  exit 1
fi

if [[ "$CREATE_IMAGE_PULL_SECRET" == "true" ]]; then
  check_dependencies kubectl
  if [[ -z "$HELM_REGISTRY_USERNAME" || -z "$HELM_REGISTRY_PASSWORD" ]]; then
    echo "Error: POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true requires HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD." >&2
    exit 1
  fi

  image_registry="${POUNDCAKE_IMAGE_REPO%%/*}"
  if [[ -z "$image_registry" || "$image_registry" == "$POUNDCAKE_IMAGE_REPO" ]]; then
    image_registry="ghcr.io"
  fi

  if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "Namespace '${NAMESPACE}' does not exist; creating it for image pull secret setup..."
    kubectl create namespace "$NAMESPACE" >/dev/null
  fi

  echo "Creating/updating image pull secret '${IMAGE_PULL_SECRET_NAME}' in namespace '${NAMESPACE}'..."
  kubectl -n "$NAMESPACE" create secret docker-registry "$IMAGE_PULL_SECRET_NAME" \
    --docker-server="$image_registry" \
    --docker-username="$HELM_REGISTRY_USERNAME" \
    --docker-password="$HELM_REGISTRY_PASSWORD" \
    --docker-email="$IMAGE_PULL_SECRET_EMAIL" \
    --dry-run=client -o yaml | kubectl apply -f -
else
  echo "Skipping image pull secret creation (POUNDCAKE_CREATE_IMAGE_PULL_SECRET=${CREATE_IMAGE_PULL_SECRET})."
fi

ensure_oci_registry_auth "$CHART_SOURCE"

HELM_CMD=(
  helm upgrade --install "$RELEASE_NAME" "$CHART_SOURCE"
  --namespace "$NAMESPACE"
  --create-namespace
  --timeout "$HELM_TIMEOUT"
  --set "image.repository=${POUNDCAKE_IMAGE_REPO}"
  --set "image.tag=${POUNDCAKE_IMAGE_TAG}"
  --set "ui.image.repository=${UI_IMAGE_REPO}"
  --set "ui.image.tag=${POUNDCAKE_IMAGE_TAG}"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "bakery.image.tag=${POUNDCAKE_IMAGE_TAG}"
)

if [[ "$CHART_SOURCE" == oci://* && -n "$CHART_VERSION" ]]; then
  HELM_CMD+=(--version "$CHART_VERSION")
fi

if [[ "$HELM_WAIT" == "true" ]]; then
  HELM_CMD+=(--wait)
fi
if [[ "$HELM_ATOMIC" == "true" ]]; then
  HELM_CMD+=(--atomic)
fi
if [[ "$HELM_CLEANUP_ON_FAIL" == "true" ]]; then
  HELM_CMD+=(--cleanup-on-fail)
fi

if [[ "$IMAGE_PULL_SECRET_ENABLED" == "true" ]]; then
  HELM_CMD+=(--set "imagePullSecrets[0].name=${IMAGE_PULL_SECRET_NAME}")
fi

echo "Installing PoundCake (legacy env installer)"
echo "  Release: ${RELEASE_NAME}"
echo "  Namespace: ${NAMESPACE}"
echo "  Chart source: ${CHART_SOURCE}"
if [[ "$CHART_SOURCE" == oci://* ]]; then
  echo "  Chart version: ${CHART_VERSION:-"(not set)"}"
fi
echo "  PoundCake image: ${POUNDCAKE_IMAGE_REPO}:${POUNDCAKE_IMAGE_TAG}"
echo "  UI image repo: ${UI_IMAGE_REPO}"
echo "  Bakery image repo: ${BAKERY_IMAGE_REPO}"
echo "  StackStorm image controls (compat): ${STACKSTORM_IMAGE_REPO}:${STACKSTORM_IMAGE_TAG}"
if [[ "$IMAGE_PULL_SECRET_ENABLED" == "true" ]]; then
  echo "  Image pull secret: enabled (${IMAGE_PULL_SECRET_NAME})"
else
  echo "  Image pull secret: disabled"
fi

echo "Executing Helm command:"
printf '%q ' "${HELM_CMD[@]}" "${EXTRA_ARGS[@]}"
echo

"${HELM_CMD[@]}" "${EXTRA_ARGS[@]}"

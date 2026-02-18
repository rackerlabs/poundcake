#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELM_DIR="$(dirname "$SCRIPT_DIR")"
source "${HELM_DIR}/scripts/common-functions.sh"

SERVICE_NAME="${POUNDCAKE_SERVICE_NAME:-poundcake}"
NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
GHCR_OWNER="${POUNDCAKE_GHCR_OWNER:-aedan}"
CHART_REPO="${POUNDCAKE_CHART_REPO:-oci://ghcr.io/${GHCR_OWNER}/charts/poundcake}"
STACKSTORM_RELEASE_NAME="${POUNDCAKE_STACKSTORM_RELEASE_NAME:-stackstorm}"
STACKSTORM_CHART_NAME="${POUNDCAKE_STACKSTORM_CHART_NAME:-stackstorm-ha}"
STACKSTORM_CHART_REPO_URL="${POUNDCAKE_STACKSTORM_CHART_REPO_URL:-https://helm.stackstorm.com/}"
STACKSTORM_VERSION_DEFAULT="${POUNDCAKE_STACKSTORM_CHART_VERSION:-1.1.0}"
APP_IMAGE_REPO="${POUNDCAKE_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake}"
UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-ui}"
BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-ghcr.io/${GHCR_OWNER}/poundcake-bakery}"
VERSION_FILE_PRIMARY="/etc/genestack/helm-chart-version.yaml"
VERSION_FILE_FALLBACK="/etc/genestack/helm-chart-versions.yaml"
GLOBAL_OVERRIDES_DIR="/etc/genestack/helm-configs/global_overrides"
POUNDCAKE_CONFIG_DIR="/etc/genestack/helm-configs/poundcake"
STACKSTORM_CONFIG_DIR="/etc/genestack/helm-configs/stackstorm"
POUNDCAKE_BASE_OVERRIDES="/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml"
STACKSTORM_BASE_OVERRIDES="/opt/genestack/base-helm-configs/stackstorm/stackstorm-helm-overrides.yaml"
STACKSTORM_DEFAULT_OVERRIDES="${HELM_DIR}/stackstorm/values-external-services.yaml"
KUSTOMIZE_RENDERER="/etc/genestack/kustomize/kustomize.sh"
KUSTOMIZE_OVERLAY_DIR="/etc/genestack/kustomize/poundcake/overlay"
KUSTOMIZE_OVERLAY_ARG="poundcake/overlay"

ROTATE_SECRETS=false
VALIDATE="${POUNDCAKE_HELM_VALIDATE:-false}"
SKIP_PREFLIGHT=false
BOOTSTRAP_DIRS=true
PASSTHROUGH_ARGS=()
POST_RENDER_ARGS=()
GLOBAL_OVERRIDE_ARGS=()
POUNDCAKE_OVERRIDE_ARGS=()
STACKSTORM_OVERRIDE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "$SKIP_PREFLIGHT" != "true" ]]; then
  perform_preflight_checks
fi

if [[ "$BOOTSTRAP_DIRS" == "true" ]]; then
  mkdir -p "$GLOBAL_OVERRIDES_DIR" "$POUNDCAKE_CONFIG_DIR" "$STACKSTORM_CONFIG_DIR"
fi

VERSION_FILE="$VERSION_FILE_PRIMARY"
if [[ ! -f "$VERSION_FILE" && -f "$VERSION_FILE_FALLBACK" ]]; then
  VERSION_FILE="$VERSION_FILE_FALLBACK"
fi

POUNDCAKE_VERSION="$(get_chart_version "poundcake" "$VERSION_FILE")"
STACKSTORM_VERSION="$(get_chart_version "stackstorm" "$VERSION_FILE" || true)"

if [[ -z "${POUNDCAKE_VERSION}" ]]; then
  echo "Error: could not determine PoundCake chart version from ${VERSION_FILE} (key: poundcake)." >&2
  exit 1
fi

STACKSTORM_VERSION="${STACKSTORM_VERSION:-$STACKSTORM_VERSION_DEFAULT}"
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

# Add post-renderer if available AND overlay exists.
if [[ -f "$KUSTOMIZE_RENDERER" && -d "$KUSTOMIZE_OVERLAY_DIR" ]]; then
  POST_RENDER_ARGS+=("--post-renderer" "$KUSTOMIZE_RENDERER")
  POST_RENDER_ARGS+=("--post-renderer-args" "$KUSTOMIZE_OVERLAY_ARG")
fi

if [[ "$ROTATE_SECRETS" == "true" ]]; then
  rotate_chart_secrets "$NAMESPACE" "$RELEASE_NAME"
fi

if [[ "$VALIDATE" == "true" ]]; then
  run_helm_validation "$CHART_REPO" "$POUNDCAKE_VERSION" "$NAMESPACE" "$RELEASE_NAME" \
    --set "stackstorm.chart.enabled=false" \
    --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}" \
    --set "stackstorm.subchart.fullnameOverride=${STACKSTORM_RELEASE_NAME}" \
    --set "stackstorm.url=${STACKSTORM_API_URL}" \
    --set "stackstorm.authUrl=${STACKSTORM_AUTH_URL}" \
    "${POUNDCAKE_OVERRIDE_ARGS[@]}" \
    "${POST_RENDER_ARGS[@]}" \
    "${PASSTHROUGH_ARGS[@]}"
fi

POUNDCAKE_PHASE1_CMD=(
  helm upgrade --install "$RELEASE_NAME" "$CHART_REPO"
  --version "$POUNDCAKE_VERSION"
  --namespace "$NAMESPACE"
  --create-namespace
  --timeout "${HELM_TIMEOUT:-$HELM_TIMEOUT_DEFAULT}"
  --set "image.repository=${APP_IMAGE_REPO}"
  --set "ui.image.repository=${UI_IMAGE_REPO}"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "stackstorm.chart.enabled=false"
  --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}"
  --set "stackstorm.subchart.fullnameOverride=${STACKSTORM_RELEASE_NAME}"
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
  --set "image.repository=${APP_IMAGE_REPO}"
  --set "ui.image.repository=${UI_IMAGE_REPO}"
  --set "bakery.image.repository=${BAKERY_IMAGE_REPO}"
  --set "stackstorm.chart.enabled=false"
  --set "stackstorm.releaseName=${STACKSTORM_RELEASE_NAME}"
  --set "stackstorm.subchart.fullnameOverride=${STACKSTORM_RELEASE_NAME}"
  --set "stackstorm.url=${STACKSTORM_API_URL}"
  --set "stackstorm.authUrl=${STACKSTORM_AUTH_URL}"
  "${POUNDCAKE_OVERRIDE_ARGS[@]}"
  "${POST_RENDER_ARGS[@]}"
)

echo "Phase 1/3: Install PoundCake prerequisites (external StackStorm mode)"
printf '%q ' "${POUNDCAKE_PHASE1_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"
echo
"${POUNDCAKE_PHASE1_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"

echo "Phase 2/3: Install StackStorm as separate release"
printf '%q ' "${STACKSTORM_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"
echo
"${STACKSTORM_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"

echo "Phase 3/3: Reconcile PoundCake after StackStorm is ready"
printf '%q ' "${POUNDCAKE_PHASE3_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"
echo
"${POUNDCAKE_PHASE3_CMD[@]}" "${PASSTHROUGH_ARGS[@]}"

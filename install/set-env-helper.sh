#!/usr/bin/env bash

# Source this file:
#   source /Users/chris.breu/code/poundcake/install/set-env-helper.sh
#
# This config targets fork-based development by default with local chart install.
# Update FORK_OWNER / tags as needed per release.

# -----------------------------------------------------------------------------
# Ownership / registry targeting
# -----------------------------------------------------------------------------
export FORK_OWNER="${FORK_OWNER:-rackerchris}"

# Optional auth for private GHCR chart/image repos.
export HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-$FORK_OWNER}"
export HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-}"
export POUNDCAKE_IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
export POUNDCAKE_CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
export POUNDCAKE_IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
export POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"

# -----------------------------------------------------------------------------
# Chart source selection
# -----------------------------------------------------------------------------
# Default local chart install from this git workspace (`./helm`).
# Keep empty to let installer pick local chart path.
export POUNDCAKE_CHART_REPO="${POUNDCAKE_CHART_REPO:-}"

# Optional explicit chart version override. If empty, installer may read
# /etc/genestack/helm-chart-versions.yaml (key: poundcake) when present.
export POUNDCAKE_CHART_VERSION="${POUNDCAKE_CHART_VERSION:-}"
export POUNDCAKE_VERSION_FILE="${POUNDCAKE_VERSION_FILE:-/etc/genestack/helm-chart-versions.yaml}"

# Optional owner hint used by installer defaults
export POUNDCAKE_GHCR_OWNER="${POUNDCAKE_GHCR_OWNER:-$FORK_OWNER}"

# -----------------------------------------------------------------------------
# Image repositories/tags
# -----------------------------------------------------------------------------
export POUNDCAKE_IMAGE_REPO="${POUNDCAKE_IMAGE_REPO:-ghcr.io/${FORK_OWNER}/poundcake}"
export POUNDCAKE_IMAGE_TAG="${POUNDCAKE_IMAGE_TAG:-latest}"

# Passed through for compatibility with existing workflows.
export POUNDCAKE_UI_IMAGE_REPO="${POUNDCAKE_UI_IMAGE_REPO:-ghcr.io/${FORK_OWNER}/poundcake-ui}"
export POUNDCAKE_UI_IMAGE_TAG="${POUNDCAKE_UI_IMAGE_TAG:-}"
export POUNDCAKE_BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-ghcr.io/${FORK_OWNER}/poundcake-bakery}"

# StackStorm image controls
export POUNDCAKE_STACKSTORM_IMAGE_REPO="${POUNDCAKE_STACKSTORM_IMAGE_REPO:-stackstorm/st2}"
export POUNDCAKE_STACKSTORM_IMAGE_TAG="${POUNDCAKE_STACKSTORM_IMAGE_TAG:-3.9.0}"

# -----------------------------------------------------------------------------
# Release behavior
# -----------------------------------------------------------------------------
export POUNDCAKE_RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
export POUNDCAKE_NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
export POUNDCAKE_HELM_TIMEOUT="${POUNDCAKE_HELM_TIMEOUT:-120m}"

# For troubleshooting, these are often set false.
export POUNDCAKE_HELM_WAIT="${POUNDCAKE_HELM_WAIT:-false}"
export POUNDCAKE_ALLOW_HOOK_WAIT="${POUNDCAKE_ALLOW_HOOK_WAIT:-false}"
export POUNDCAKE_HELM_ATOMIC="${POUNDCAKE_HELM_ATOMIC:-false}"
export POUNDCAKE_HELM_CLEANUP_ON_FAIL="${POUNDCAKE_HELM_CLEANUP_ON_FAIL:-false}"
export POUNDCAKE_HELM_VALIDATE="${POUNDCAKE_HELM_VALIDATE:-false}"

# Values/overlay inputs consumed by installer defaults.
export POUNDCAKE_BASE_OVERRIDES="${POUNDCAKE_BASE_OVERRIDES:-/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml}"
export POUNDCAKE_GLOBAL_OVERRIDES_DIR="${POUNDCAKE_GLOBAL_OVERRIDES_DIR:-/etc/genestack/helm-configs/global_overrides}"
export POUNDCAKE_SERVICE_CONFIG_DIR="${POUNDCAKE_SERVICE_CONFIG_DIR:-/etc/genestack/helm-configs/poundcake}"
export POUNDCAKE_HELM_POST_RENDERER="${POUNDCAKE_HELM_POST_RENDERER:-/etc/genestack/kustomize/kustomize.sh}"
export POUNDCAKE_HELM_POST_RENDERER_ARGS="${POUNDCAKE_HELM_POST_RENDERER_ARGS:-poundcake/overlay}"
export POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR="${POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR:-/etc/genestack/kustomize/poundcake/overlay}"

# -----------------------------------------------------------------------------
# Optional profile switch examples
# -----------------------------------------------------------------------------
# Optional OCI chart profile example:
#   export POUNDCAKE_CHART_REPO="oci://ghcr.io/${FORK_OWNER}/charts/poundcake"
#   export POUNDCAKE_CHART_VERSION="0.1.0"
#
# Production owner example:
#   export FORK_OWNER="rackerlabs"
#   export POUNDCAKE_CHART_REPO="oci://ghcr.io/rackerlabs/charts/poundcake"
#   export POUNDCAKE_IMAGE_REPO="ghcr.io/rackerlabs/poundcake"
#   export POUNDCAKE_UI_IMAGE_REPO="ghcr.io/rackerlabs/poundcake-ui"
#   export POUNDCAKE_BAKERY_IMAGE_REPO="ghcr.io/rackerlabs/poundcake-bakery"

if [[ -n "${POUNDCAKE_CHART_REPO}" ]]; then
  CHART_SOURCE_DISPLAY="${POUNDCAKE_CHART_REPO}"
  CHART_MODE_DISPLAY="oci/explicit"
else
  CHART_SOURCE_DISPLAY="local (./helm)"
  CHART_MODE_DISPLAY="local"
fi

echo "PoundCake env helper loaded."
echo "  Chart mode:  ${CHART_MODE_DISPLAY}"
echo "  Chart repo:  ${CHART_SOURCE_DISPLAY}"
echo "  Image repo:  ${POUNDCAKE_IMAGE_REPO}:${POUNDCAKE_IMAGE_TAG}"
echo "  Namespace:   ${POUNDCAKE_NAMESPACE}"
echo "  Release:     ${POUNDCAKE_RELEASE_NAME}"
echo "  Pull secret: ${POUNDCAKE_IMAGE_PULL_SECRET_NAME} (enabled=${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED}, create=${POUNDCAKE_CREATE_IMAGE_PULL_SECRET})"
echo "  Helm wait:   ${POUNDCAKE_HELM_WAIT} (allow_hook_wait=${POUNDCAKE_ALLOW_HOOK_WAIT})"

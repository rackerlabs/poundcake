#!/usr/bin/env bash

# Source this file:
#   source /Users/chris.breu/code/poundcake/install/set-env-helper.sh
#
# This config targets fork-based development by default.
# Update FORK_OWNER / tags as needed per release.

# -----------------------------------------------------------------------------
# Ownership / registry targeting
# -----------------------------------------------------------------------------
export FORK_OWNER="${FORK_OWNER:-rackerchris}"

# Optional OCI auth for private chart/image repos
export HELM_REGISTRY_USERNAME="${HELM_REGISTRY_USERNAME:-$FORK_OWNER}"
export HELM_REGISTRY_PASSWORD="${HELM_REGISTRY_PASSWORD:-<password>}"
export POUNDCAKE_IMAGE_PULL_SECRET_NAME="${POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull}"
export POUNDCAKE_CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true}"
export POUNDCAKE_IMAGE_PULL_SECRET_EMAIL="${POUNDCAKE_IMAGE_PULL_SECRET_EMAIL:-noreply@local}"
export POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true}"
export POUNDCAKE_IMAGE_CONTRACT_CHECK="${POUNDCAKE_IMAGE_CONTRACT_CHECK:-true}"

# -----------------------------------------------------------------------------
# Chart source selection
# -----------------------------------------------------------------------------
# Use a local chart path for fork testing
export POUNDCAKE_CHART_REPO="${POUNDCAKE_CHART_REPO:-/opt/poundcake/helm}"
# Optional OCI chart repo example:
# export POUNDCAKE_CHART_REPO="${POUNDCAKE_CHART_REPO:-oci://ghcr.io/${FORK_OWNER}/charts/poundcake-standalone}"

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
export POUNDCAKE_BAKERY_IMAGE_REPO="${POUNDCAKE_BAKERY_IMAGE_REPO:-ghcr.io/${FORK_OWNER}/poundcake-bakery}"

# StackStorm image controls (legacy compatibility)
export POUNDCAKE_STACKSTORM_IMAGE_REPO="${POUNDCAKE_STACKSTORM_IMAGE_REPO:-stackstorm/st2}"
export POUNDCAKE_STACKSTORM_IMAGE_TAG="${POUNDCAKE_STACKSTORM_IMAGE_TAG:-3.9.0}"

# -----------------------------------------------------------------------------
# Release behavior
# -----------------------------------------------------------------------------
export POUNDCAKE_RELEASE_NAME="${POUNDCAKE_RELEASE_NAME:-poundcake}"
export POUNDCAKE_NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"
export POUNDCAKE_OPERATORS_MODE="${POUNDCAKE_OPERATORS_MODE:-install-missing}"
export POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME="${POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME:-redis-operator}"
export POUNDCAKE_REDIS_OPERATOR_NAMESPACE="${POUNDCAKE_REDIS_OPERATOR_NAMESPACE:-redis-systems}"
export POUNDCAKE_HELM_TIMEOUT="${POUNDCAKE_HELM_TIMEOUT:-120m}"
export POUNDCAKE_HELM_WAIT="${POUNDCAKE_HELM_WAIT:-false}"
export POUNDCAKE_HELM_ATOMIC="${POUNDCAKE_HELM_ATOMIC:-false}"
export POUNDCAKE_HELM_CLEANUP_ON_FAIL="${POUNDCAKE_HELM_CLEANUP_ON_FAIL:-false}"

echo "PoundCake env helper loaded."
echo "  Chart repo:  ${POUNDCAKE_CHART_REPO}"
echo "  Image repo:  ${POUNDCAKE_IMAGE_REPO}:${POUNDCAKE_IMAGE_TAG}"
echo "  Namespace:   ${POUNDCAKE_NAMESPACE}"
echo "  Release:     ${POUNDCAKE_RELEASE_NAME}"
echo "  Operators mode: ${POUNDCAKE_OPERATORS_MODE}"
echo "  Redis operator release: ${POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME} (ns=${POUNDCAKE_REDIS_OPERATOR_NAMESPACE})"
echo "  Pull secret: ${POUNDCAKE_IMAGE_PULL_SECRET_NAME} (enabled=${POUNDCAKE_IMAGE_PULL_SECRET_ENABLED}, create=${POUNDCAKE_CREATE_IMAGE_PULL_SECRET})"
echo "  Image contract check: ${POUNDCAKE_IMAGE_CONTRACT_CHECK}"

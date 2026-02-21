#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/../bin/install-poundcake-with-env.sh"
WRAPPER_SCRIPT="${SCRIPT_DIR}/../../install/install-helm.sh"

echo "Checking installer hardening, validation flow, and wrapper pass-through..."

# Core safety baseline
rg -q 'HELM_WAIT="\$\{POUNDCAKE_HELM_WAIT:-false\}"' "${INSTALL_SCRIPT}"
rg -q 'ALLOW_HOOK_WAIT="\$\{POUNDCAKE_ALLOW_HOOK_WAIT:-false\}"' "${INSTALL_SCRIPT}"
rg -q 'post-install/post-upgrade hooks' "${INSTALL_SCRIPT}"
rg -q 'Using --wait/--atomic can deadlock' "${INSTALL_SCRIPT}"

# Preflight framework + flags
rg -q '^check_dependencies\(\)' "${INSTALL_SCRIPT}"
rg -q '^check_cluster_connection\(\)' "${INSTALL_SCRIPT}"
rg -q '^perform_preflight_checks\(\)' "${INSTALL_SCRIPT}"
rg -q -- '--skip-preflight' "${INSTALL_SCRIPT}"
rg -q 'perform_preflight_checks' "${INSTALL_SCRIPT}"

# Validation mode
rg -q '^run_helm_validation\(\)' "${INSTALL_SCRIPT}"
rg -q -- '--validate' "${INSTALL_SCRIPT}"
rg -q 'POUNDCAKE_HELM_VALIDATE' "${INSTALL_SCRIPT}"
rg -q 'helm lint' "${INSTALL_SCRIPT}"
rg -q 'helm template .*--debug' "${INSTALL_SCRIPT}"

# Secret rotation
rg -q '^rotate_chart_secrets\(\)' "${INSTALL_SCRIPT}"
rg -q -- '--rotate-secrets' "${INSTALL_SCRIPT}"
rg -Fq 'kubectl -n "${namespace}" delete secret "${s}" --ignore-not-found' "${INSTALL_SCRIPT}"

# Pull-secret behavior and rendered-manifest guard
rg -q 'IMAGE_PULL_SECRET_NAME="\$\{POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull\}"' "${INSTALL_SCRIPT}"
rg -q 'CREATE_IMAGE_PULL_SECRET="\$\{POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true\}"' "${INSTALL_SCRIPT}"
rg -q 'IMAGE_PULL_SECRET_ENABLED="\$\{POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true\}"' "${INSTALL_SCRIPT}"
rg -q 'POUNDCAKE_IMAGE_DIGEST="\$\{POUNDCAKE_IMAGE_DIGEST:-\}"' "${INSTALL_SCRIPT}"
rg -q 'PACK_SYNC_ENDPOINT="\$\{POUNDCAKE_PACK_SYNC_ENDPOINT:-http://poundcake-api:8000/api/v1/cook/packs\}"' "${INSTALL_SCRIPT}"
rg -q 'create secret docker-registry' "${INSTALL_SCRIPT}"
rg -q "kubectl get namespace" "${INSTALL_SCRIPT}"
rg -q "kubectl create namespace" "${INSTALL_SCRIPT}"
rg -q 'poundcakeImage\.pullSecrets\[0\]=' "${INSTALL_SCRIPT}"
rg -q 'Rendered PoundCake manifests do not include imagePullSecrets' "${INSTALL_SCRIPT}"
rg -q 'requires HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD' "${INSTALL_SCRIPT}"
rg -q 'Refusing install to avoid anonymous private-registry pulls' "${INSTALL_SCRIPT}"
rg -q '^validate_image_pin_input\(\)' "${INSTALL_SCRIPT}"
rg -q '^verify_rendered_endpoint_contract\(\)' "${INSTALL_SCRIPT}"
rg -q 'Image pin required: set POUNDCAKE_IMAGE_TAG or POUNDCAKE_IMAGE_DIGEST' "${INSTALL_SCRIPT}"
rg -q 'poundcake-api probes must target /api/v1/ready and /api/v1/live' "${INSTALL_SCRIPT}"

# OCI auth fallback chain
rg -q 'GHCR_USERNAME' "${INSTALL_SCRIPT}"
rg -q 'GITHUB_ACTOR' "${INSTALL_SCRIPT}"
rg -q 'GHCR_TOKEN' "${INSTALL_SCRIPT}"
rg -q 'CR_PAT' "${INSTALL_SCRIPT}"
rg -q 'GITHUB_TOKEN' "${INSTALL_SCRIPT}"

# Override layering + post-renderer support
rg -q 'POUNDCAKE_BASE_OVERRIDES' "${INSTALL_SCRIPT}"
rg -q 'POUNDCAKE_GLOBAL_OVERRIDES_DIR' "${INSTALL_SCRIPT}"
rg -q 'POUNDCAKE_SERVICE_CONFIG_DIR' "${INSTALL_SCRIPT}"
rg -q '^collect_yaml_files\(\)' "${INSTALL_SCRIPT}"
rg -q -- '--post-renderer' "${INSTALL_SCRIPT}"
rg -q -- '--post-renderer-args' "${INSTALL_SCRIPT}"
rg -q -- '--set-string "stackstormPackSync.endpoint=' "${INSTALL_SCRIPT}"

# Version-file fallback sequence
rg -q 'POUNDCAKE_VERSION_FILE' "${INSTALL_SCRIPT}"
rg -q '/etc/genestack/helm-chart-version.yaml' "${INSTALL_SCRIPT}"
rg -q '/etc/genestack/helm-chart-versions.yaml' "${INSTALL_SCRIPT}"

# Wrapper should invoke the installer directly (no chart no-op flags)
rg -q 'exec "\$PROJECT_ROOT/helm/bin/install-poundcake-with-env.sh" "\$@"' "${WRAPPER_SCRIPT}"

echo "Installer and wrapper checks passed!"

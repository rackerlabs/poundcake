#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/../bin/install-poundcake.sh"

echo "Checking installer wait defaults and hook guardrail..."

rg -q 'HELM_WAIT="\$\{POUNDCAKE_HELM_WAIT:-false\}"' "${INSTALL_SCRIPT}"
rg -q 'ALLOW_HOOK_WAIT="\$\{POUNDCAKE_ALLOW_HOOK_WAIT:-false\}"' "${INSTALL_SCRIPT}"
rg -q 'post-install/post-upgrade hooks' "${INSTALL_SCRIPT}"
rg -q 'Using --wait/--atomic can deadlock' "${INSTALL_SCRIPT}"
rg -q 'IMAGE_PULL_SECRET_NAME="\$\{POUNDCAKE_IMAGE_PULL_SECRET_NAME:-ghcr-pull\}"' "${INSTALL_SCRIPT}"
rg -q 'CREATE_IMAGE_PULL_SECRET="\$\{POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-true\}"' "${INSTALL_SCRIPT}"
rg -q 'IMAGE_PULL_SECRET_ENABLED="\$\{POUNDCAKE_IMAGE_PULL_SECRET_ENABLED:-true\}"' "${INSTALL_SCRIPT}"
rg -q 'create secret docker-registry' "${INSTALL_SCRIPT}"
rg -q "kubectl get namespace" "${INSTALL_SCRIPT}"
rg -q "kubectl create namespace" "${INSTALL_SCRIPT}"
rg -q 'poundcakeImage\.pullSecrets\[0\]=' "${INSTALL_SCRIPT}"
rg -q 'rendered PoundCake manifests do not include imagePullSecrets' "${INSTALL_SCRIPT}"
rg -q 'requires HELM_REGISTRY_USERNAME and HELM_REGISTRY_PASSWORD' "${INSTALL_SCRIPT}"

echo "Installer wait/guardrail checks passed!"

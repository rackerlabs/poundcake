#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/../../install/install-poundcake-helm.sh"
INSTALLER="${SCRIPT_DIR}/../bin/install-poundcake.sh"
HELPER="${SCRIPT_DIR}/../../install/set-env-helper.sh"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

assert_contains() {
  local needle="$1"
  local file="$2"
  if ! rg -Fq -- "${needle}" "${file}"; then
    echo "Expected to find: ${needle}" >&2
    echo "In file: ${file}" >&2
    echo "--- file contents ---" >&2
    cat "${file}" >&2 || true
    echo "---------------------" >&2
    fail "missing expected content"
  fi
}

assert_not_contains() {
  local needle="$1"
  local file="$2"
  if rg -Fq -- "${needle}" "${file}"; then
    echo "Did not expect to find: ${needle}" >&2
    echo "In file: ${file}" >&2
    echo "--- file contents ---" >&2
    cat "${file}" >&2 || true
    echo "---------------------" >&2
    fail "unexpected content present"
  fi
}

echo "Checking PoundCake installer wrapper..."
[[ -x "${WRAPPER}" ]] || fail "missing ${WRAPPER}"
assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "$@"' "${WRAPPER}"
assert_not_contains "install-bakery-helm.sh" "${WRAPPER}"

echo "Checking rendered manifest probe contract..."
[[ -x "${INSTALLER}" ]] || fail "missing ${INSTALLER}"
assert_contains '/api/v1/ready' "${INSTALLER}"
assert_contains '/api/v1/live' "${INSTALLER}"
assert_not_contains '/api/v1/health.' "${INSTALLER}"
assert_contains 'NAMESPACE="${POUNDCAKE_NAMESPACE:-rackspace}"' "${INSTALLER}"
assert_contains 'CREATE_IMAGE_PULL_SECRET="${POUNDCAKE_CREATE_IMAGE_PULL_SECRET:-false}"' "${INSTALLER}"
assert_contains '"/etc/genestack/helm-chart-versions.yaml"' "${INSTALLER}"
assert_contains 'GLOBAL_OVERRIDES_DIR="${POUNDCAKE_GLOBAL_OVERRIDES_DIR:-/etc/genestack/helm-configs/global_overrides}"' "${INSTALLER}"
assert_contains 'SERVICE_CONFIG_DIR="${POUNDCAKE_SERVICE_CONFIG_DIR:-/etc/genestack/helm-configs/poundcake}"' "${INSTALLER}"
assert_contains 'POST_RENDERER="${POUNDCAKE_HELM_POST_RENDERER:-/etc/genestack/kustomize/kustomize.sh}"' "${INSTALLER}"
assert_not_contains '/etc/poundcake/helm-chart-versions.yaml' "${INSTALLER}"
assert_not_contains '/etc/poundcake/helm-configs/poundcake' "${INSTALLER}"

echo "Checking environment helper defaults..."
assert_contains 'export POUNDCAKE_GLOBAL_OVERRIDES_DIR="${POUNDCAKE_GLOBAL_OVERRIDES_DIR:-/etc/genestack/helm-configs/global_overrides}"' "${HELPER}"
assert_contains 'export POUNDCAKE_SERVICE_CONFIG_DIR="${POUNDCAKE_SERVICE_CONFIG_DIR:-/etc/genestack/helm-configs/poundcake}"' "${HELPER}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
TARGET_OUT="${TMP_DIR}/target.out"

echo "Validating --target rejection message..."
if "${WRAPPER}" --target bakery >"${TARGET_OUT}" 2>&1; then
  fail "expected --target to fail"
fi

assert_contains "install-poundcake-helm.sh no longer supports --target." "${TARGET_OUT}"
assert_contains "PoundCake now installs only PoundCake." "${TARGET_OUT}"
assert_contains "Install Bakery from the standalone bakery repo" "${TARGET_OUT}"

echo "[PASS] PoundCake install wrapper checks passed"

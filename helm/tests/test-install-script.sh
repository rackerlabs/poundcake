#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/../../install/install-poundcake-helm.sh"

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

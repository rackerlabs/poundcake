#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOMATED_SETUP="${SCRIPT_DIR}/../files/scripts/automated-setup.sh"

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

assert_before() {
  local first="$1"
  local second="$2"
  local file="$3"
  local first_line
  local second_line

  first_line="$(rg -n -F -- "${first}" "${file}" | head -n1 | cut -d: -f1)"
  second_line="$(rg -n -F -- "${second}" "${file}" | head -n1 | cut -d: -f1)"

  if [ -z "${first_line}" ] || [ -z "${second_line}" ] || [ "${first_line}" -ge "${second_line}" ]; then
    echo "Expected '${first}' to appear before '${second}' in ${file}" >&2
    echo "--- file contents ---" >&2
    cat "${file}" >&2 || true
    echo "---------------------" >&2
    fail "unexpected ordering"
  fi
}

assert_line_count() {
  local expected="$1"
  local needle="$2"
  local file="$3"
  local actual

  actual="$(rg -c -F -- "${needle}" "${file}" || true)"
  if [ "${actual}" != "${expected}" ]; then
    echo "Expected ${expected} occurrences of '${needle}' in ${file}, found ${actual}" >&2
    echo "--- file contents ---" >&2
    cat "${file}" >&2 || true
    echo "---------------------" >&2
    fail "unexpected match count"
  fi
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
STUB_BIN="${TMP_DIR}/bin"
APP_CONFIG="${TMP_DIR}/app-config"
mkdir -p "${STUB_BIN}" "${APP_CONFIG}"

cat > "${STUB_BIN}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '200'
EOF
chmod +x "${STUB_BIN}/curl"

cat > "${STUB_BIN}/st2" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "st2 $*" >> "${ST2_LOG_PATH:?}"
if [[ "${1:-}" == "auth" ]]; then
  printf '12345678901234567890'
  exit 0
fi
if [[ "${1:-}" == "apikey" && "${2:-}" == "create" ]]; then
  printf 'generated-api-key'
  exit 0
fi
if [[ "${1:-}" == "action" && "${2:-}" == "get" && "${3:-}" == "packs.install" ]]; then
  state_file="${ST2_PACKS_INSTALL_STATE_FILE:-}"
  if [[ -n "${state_file}" ]]; then
    current_attempt=0
    if [[ -f "${state_file}" ]]; then
      current_attempt="$(cat "${state_file}")"
    fi
    current_attempt=$((current_attempt + 1))
    printf '%s' "${current_attempt}" > "${state_file}"
    ready_after="${ST2_PACKS_INSTALL_READY_AFTER:-1}"
    if [[ "${ready_after}" -gt 0 && "${current_attempt}" -ge "${ready_after}" ]]; then
      exit 0
    fi
    exit 1
  fi
  exit 0
fi
if [[ "${1:-}" == "key" && "${2:-}" == "set" ]]; then
  exit 0
fi
if [[ "${1:-}" == "action" && "${2:-}" == "list" ]]; then
  exit 0
fi
if [[ "${1:-}" == "pack" && "${2:-}" == "list" ]]; then
  exit 0
fi
echo "unexpected st2 invocation: $*" >&2
exit 1
EOF
chmod +x "${STUB_BIN}/st2"

cat > "${STUB_BIN}/st2-register-content" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
chmod +x "${STUB_BIN}/st2-register-content"

cat > "${STUB_BIN}/install-third-party-packs.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
chmod +x "${STUB_BIN}/install-third-party-packs.sh"

run_setup() {
  local out_file="$1"
  shift
  env \
    PATH="${STUB_BIN}:$PATH" \
    ST2_LOG_PATH="${TMP_DIR}/st2.log" \
    ST2_AUTH_USER="st2admin" \
    ST2_AUTH_PASSWORD="secret" \
    ST2_INSTALL_KUBERNETES_PACK="true" \
    ST2_INSTALL_OPENSTACK_PACK="false" \
    ST2_KUBERNETES_RUNTIME_HOST="https://cluster.local" \
    ST2_KUBERNETES_RUNTIME_VERIFY_SSL="false" \
    APP_CONFIG_DIR="${APP_CONFIG}" \
    THIRD_PARTY_INSTALLER_SCRIPT="${STUB_BIN}/install-third-party-packs.sh" \
    "$@" \
    bash "${AUTOMATED_SETUP}" >"${out_file}" 2>&1
}

SEED_OUT="${TMP_DIR}/seed.out"
SKIP_OUT="${TMP_DIR}/skip.out"
WAIT_OUT="${TMP_DIR}/wait.out"
TIMEOUT_OUT="${TMP_DIR}/timeout.out"
TOKEN_FILE="${TMP_DIR}/sa.token"
PACKS_INSTALL_STATE="${TMP_DIR}/packs.install.state"
INSTALLER_LOG="${TMP_DIR}/installer.log"
printf 'k8s-token-value' > "${TOKEN_FILE}"

cat > "${STUB_BIN}/install-third-party-packs.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'installer invoked\n' >> "${INSTALLER_LOG_PATH:?}"
exit 0
EOF
chmod +x "${STUB_BIN}/install-third-party-packs.sh"

echo "Checking datastore seeding path..."
: > "${TMP_DIR}/st2.log"
rm -f "${PACKS_INSTALL_STATE}" "${INSTALLER_LOG}"
run_setup "${SEED_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}" ST2_PACKS_INSTALL_STATE_FILE="${PACKS_INSTALL_STATE}" INSTALLER_LOG_PATH="${INSTALLER_LOG}"
assert_contains "Seeding StackStorm datastore keys for kubernetes pack..." "${SEED_OUT}"
assert_contains "st2 key set kubernetes.host https://cluster.local" "${TMP_DIR}/st2.log"
assert_contains "st2 key set kubernetes.bearer_token k8s-token-value" "${TMP_DIR}/st2.log"
assert_contains "st2 key set kubernetes.verify_ssl false" "${TMP_DIR}/st2.log"
assert_contains "[OK] StackStorm action packs.install is available." "${SEED_OUT}"

echo "Checking datastore seeding skip path..."
: > "${TMP_DIR}/st2.log"
rm -f "${PACKS_INSTALL_STATE}" "${INSTALLER_LOG}"
run_setup "${SKIP_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}" ST2_KUBERNETES_RUNTIME_SEED_DATASTORE="false" ST2_PACKS_INSTALL_STATE_FILE="${PACKS_INSTALL_STATE}" INSTALLER_LOG_PATH="${INSTALLER_LOG}"
assert_contains "Skipping Kubernetes datastore seeding (disabled)." "${SKIP_OUT}"
assert_not_contains "st2 key set kubernetes.host" "${TMP_DIR}/st2.log"

echo "Checking pack install readiness wait path..."
: > "${TMP_DIR}/st2.log"
rm -f "${PACKS_INSTALL_STATE}" "${INSTALLER_LOG}"
run_setup "${WAIT_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}" ST2_PACKS_INSTALL_STATE_FILE="${PACKS_INSTALL_STATE}" ST2_PACKS_INSTALL_READY_AFTER="3" INSTALLER_LOG_PATH="${INSTALLER_LOG}"
assert_contains "Waiting for StackStorm pack-management actions to be registered..." "${WAIT_OUT}"
assert_contains "[WARN] packs.install is not registered yet (attempt 1/30); waiting 4s before installing optional packs." "${WAIT_OUT}"
assert_contains "[WARN] packs.install is not registered yet (attempt 2/30); waiting 4s before installing optional packs." "${WAIT_OUT}"
assert_contains "[OK] StackStorm action packs.install is available." "${WAIT_OUT}"
assert_contains "installer invoked" "${INSTALLER_LOG}"
assert_before "[OK] StackStorm action packs.install is available." "Installing enabled third-party packs..." "${WAIT_OUT}"
assert_line_count 3 "st2 action get packs.install" "${TMP_DIR}/st2.log"

echo "Checking pack install readiness timeout path..."
: > "${TMP_DIR}/st2.log"
rm -f "${PACKS_INSTALL_STATE}" "${INSTALLER_LOG}"
if run_setup "${TIMEOUT_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}" ST2_PACKS_INSTALL_STATE_FILE="${PACKS_INSTALL_STATE}" ST2_PACKS_INSTALL_READY_AFTER="999" ST2_PACK_INSTALL_READY_RETRIES="2" ST2_PACK_INSTALL_READY_DELAY_SECONDS="0" INSTALLER_LOG_PATH="${INSTALLER_LOG}"; then
  fail "expected packs.install readiness timeout to fail"
fi
assert_contains "[ERROR] StackStorm action packs.install did not become available after 2 attempts." "${TIMEOUT_OUT}"
assert_contains "stackstorm-register may still be publishing core actions" "${TIMEOUT_OUT}"
if [ -f "${INSTALLER_LOG}" ] && [ -s "${INSTALLER_LOG}" ]; then
  fail "installer should not run when packs.install never becomes available"
fi

echo "[PASS] automated-setup Kubernetes datastore seeding checks passed"

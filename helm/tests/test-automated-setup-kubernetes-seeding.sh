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
if [[ "${1:-}" == "auth" ]]; then
  printf '12345678901234567890'
  exit 0
fi
if [[ "${1:-}" == "apikey" && "${2:-}" == "create" ]]; then
  printf 'generated-api-key'
  exit 0
fi
if [[ "${1:-}" == "key" && "${2:-}" == "set" ]]; then
  printf 'st2 key set %s %s\n' "$3" "$4" >> "${ST2_LOG_PATH:?}"
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
TOKEN_FILE="${TMP_DIR}/sa.token"
printf 'k8s-token-value' > "${TOKEN_FILE}"

echo "Checking datastore seeding path..."
: > "${TMP_DIR}/st2.log"
run_setup "${SEED_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}"
assert_contains "Seeding StackStorm datastore keys for kubernetes pack..." "${SEED_OUT}"
assert_contains "st2 key set kubernetes.host https://cluster.local" "${TMP_DIR}/st2.log"
assert_contains "st2 key set kubernetes.bearer_token k8s-token-value" "${TMP_DIR}/st2.log"
assert_contains "st2 key set kubernetes.verify_ssl false" "${TMP_DIR}/st2.log"

echo "Checking datastore seeding skip path..."
: > "${TMP_DIR}/st2.log"
run_setup "${SKIP_OUT}" env KUBERNETES_SERVICEACCOUNT_TOKEN_PATH="${TOKEN_FILE}" ST2_KUBERNETES_RUNTIME_SEED_DATASTORE="false"
assert_contains "Skipping Kubernetes datastore seeding (disabled)." "${SKIP_OUT}"
assert_not_contains "st2 key set kubernetes.host" "${TMP_DIR}/st2.log"

echo "[PASS] automated-setup Kubernetes datastore seeding checks passed"

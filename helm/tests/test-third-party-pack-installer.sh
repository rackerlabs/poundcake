#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="${SCRIPT_DIR}/../files/st2-init/install-third-party-packs.sh"

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
FAKE_ROOT="${TMP_DIR}/root"
mkdir -p "${STUB_BIN}" "${FAKE_ROOT}/packs" "${FAKE_ROOT}/virtualenvs"

cat > "${STUB_BIN}/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
dest="${@: -1}"
mkdir -p "${dest}"
cat > "${dest}/pack.yaml" <<'PACK'
name: stub
PACK
cat > "${dest}/requirements.txt" <<'REQ'
requests
REQ
EOF
chmod +x "${STUB_BIN}/git"

cat > "${STUB_BIN}/python3" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
  dest="${@: -1}"
  mkdir -p "${dest}/bin"
  cat > "${dest}/bin/pip" <<'PIP'
#!/usr/bin/env bash
set -euo pipefail
exit 0
PIP
  chmod +x "${dest}/bin/pip"
  exit 0
fi
echo "unexpected python3 invocation: $*" >&2
exit 1
EOF
chmod +x "${STUB_BIN}/python3"

run_installer() {
  local out_file="$1"
  shift
  env \
    PATH="${STUB_BIN}:$PATH" \
    ST2_PACK_ROOT="${FAKE_ROOT}" \
    ST2_INSTALL_KUBERNETES_PACK=true \
    ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" \
    "$@" \
    "${INSTALLER}" >"${out_file}" 2>&1
}

FRESH_OUT="${TMP_DIR}/fresh.out"
REUSE_OUT="${TMP_DIR}/reuse.out"
PARTIAL_OUT="${TMP_DIR}/partial.out"
LOST_FOUND_PACK_OUT="${TMP_DIR}/lost-found-pack.out"
LOST_FOUND_VENV_OUT="${TMP_DIR}/lost-found-venv.out"

echo "Checking fresh install path..."
run_installer "${FRESH_OUT}" bash
assert_contains "Installing StackStorm pack kubernetes from https://example.invalid/stackstorm-kubernetes.git" "${FRESH_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${FRESH_OUT}"
[[ -f "${FAKE_ROOT}/packs/kubernetes/pack.yaml" ]] || fail "expected pack content to be created"
[[ -x "${FAKE_ROOT}/virtualenvs/kubernetes/bin/pip" ]] || fail "expected virtualenv pip stub to exist"

echo "Checking full reuse path..."
run_installer "${REUSE_OUT}" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${REUSE_OUT}"
assert_contains "Reusing existing StackStorm virtualenv directory ${FAKE_ROOT}/virtualenvs/kubernetes" "${REUSE_OUT}"
assert_not_contains "Installing StackStorm pack kubernetes from https://example.invalid/stackstorm-kubernetes.git" "${REUSE_OUT}"
assert_not_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${REUSE_OUT}"

echo "Checking partial reuse path..."
rm -rf "${FAKE_ROOT}/virtualenvs/kubernetes"
run_installer "${PARTIAL_OUT}" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${PARTIAL_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${PARTIAL_OUT}"

echo "Checking lost+found-only pack directory path..."
rm -rf "${FAKE_ROOT}/packs/kubernetes" "${FAKE_ROOT}/virtualenvs/kubernetes"
mkdir -p "${FAKE_ROOT}/packs/kubernetes/lost+found" "${FAKE_ROOT}/virtualenvs/kubernetes"
run_installer "${LOST_FOUND_PACK_OUT}" bash
assert_contains "Installing StackStorm pack kubernetes from https://example.invalid/stackstorm-kubernetes.git" "${LOST_FOUND_PACK_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${LOST_FOUND_PACK_OUT}"
[[ -f "${FAKE_ROOT}/packs/kubernetes/pack.yaml" ]] || fail "expected pack install to ignore lost+found"

echo "Checking lost+found-only virtualenv directory path..."
rm -rf "${FAKE_ROOT}/virtualenvs/kubernetes"
mkdir -p "${FAKE_ROOT}/virtualenvs/kubernetes/lost+found"
run_installer "${LOST_FOUND_VENV_OUT}" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${LOST_FOUND_VENV_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${LOST_FOUND_VENV_OUT}"
[[ -x "${FAKE_ROOT}/virtualenvs/kubernetes/bin/pip" ]] || fail "expected virtualenv creation to ignore lost+found"

echo "[PASS] Third-party StackStorm pack installer checks passed"

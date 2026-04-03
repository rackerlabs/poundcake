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

cat > "${STUB_BIN}/st2" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "pack" && "${2:-}" == "install" ]]; then
  printf '%s\n' "$3" >> "${ST2_LOG_PATH:?}"
  exit 0
fi
echo "unexpected st2 invocation: $*" >&2
exit 1
EOF
chmod +x "${STUB_BIN}/st2"

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

cat > "${STUB_BIN}/virtualenv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
dest="${@: -1}"
mkdir -p "${dest}/bin"
cat > "${dest}/bin/pip" <<'PIP'
#!/usr/bin/env bash
set -euo pipefail
exit 0
PIP
chmod +x "${dest}/bin/pip"
exit 0
EOF
chmod +x "${STUB_BIN}/virtualenv"

run_installer() {
  local out_file="$1"
  shift
  env \
    PATH="${STUB_BIN}:$PATH" \
    ST2_PACK_ROOT="${FAKE_ROOT}" \
    ST2_INSTALL_KUBERNETES_PACK=true \
    "$@" \
    "${INSTALLER}" >"${out_file}" 2>&1
}

EXCHANGE_OUT="${TMP_DIR}/exchange.out"
EXCHANGE_VERSION_OUT="${TMP_DIR}/exchange-version.out"
GIT_FRESH_OUT="${TMP_DIR}/git-fresh.out"
GIT_REUSE_OUT="${TMP_DIR}/git-reuse.out"
GIT_PARTIAL_OUT="${TMP_DIR}/git-partial.out"
GIT_LOST_FOUND_PACK_OUT="${TMP_DIR}/git-lost-found-pack.out"
GIT_LOST_FOUND_VENV_OUT="${TMP_DIR}/git-lost-found-venv.out"
GIT_VERSION_OUT="${TMP_DIR}/git-version.out"
MISSING_REPO_OUT="${TMP_DIR}/missing-repo.out"
BAD_SOURCE_OUT="${TMP_DIR}/bad-source.out"
ST2_LOG="${TMP_DIR}/st2.log"

echo "Checking exchange install without version..."
: > "${ST2_LOG}"
run_installer "${EXCHANGE_OUT}" env ST2_LOG_PATH="${ST2_LOG}" bash
assert_contains "Installing StackStorm pack kubernetes from StackStorm Exchange" "${EXCHANGE_OUT}"
assert_contains "kubernetes" "${ST2_LOG}"
assert_not_contains "Creating StackStorm virtualenv" "${EXCHANGE_OUT}"

echo "Checking exchange install with version..."
: > "${ST2_LOG}"
run_installer "${EXCHANGE_VERSION_OUT}" env ST2_LOG_PATH="${ST2_LOG}" ST2_INSTALL_KUBERNETES_PACK_VERSION="1.2.3" bash
assert_contains "Installing StackStorm pack kubernetes=1.2.3 from StackStorm Exchange" "${EXCHANGE_VERSION_OUT}"
assert_contains "kubernetes=1.2.3" "${ST2_LOG}"

echo "Checking git install fresh path..."
run_installer "${GIT_FRESH_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" bash
assert_contains "Installing StackStorm pack kubernetes from https://example.invalid/stackstorm-kubernetes.git" "${GIT_FRESH_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${GIT_FRESH_OUT}"
[[ -f "${FAKE_ROOT}/packs/kubernetes/pack.yaml" ]] || fail "expected pack content to be created"
[[ -x "${FAKE_ROOT}/virtualenvs/kubernetes/bin/pip" ]] || fail "expected virtualenv pip stub to exist"

echo "Checking git full reuse path..."
run_installer "${GIT_REUSE_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${GIT_REUSE_OUT}"
assert_contains "Reusing existing StackStorm virtualenv directory ${FAKE_ROOT}/virtualenvs/kubernetes" "${GIT_REUSE_OUT}"

echo "Checking git partial reuse path..."
rm -rf "${FAKE_ROOT}/virtualenvs/kubernetes"
run_installer "${GIT_PARTIAL_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${GIT_PARTIAL_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${GIT_PARTIAL_OUT}"

echo "Checking git lost+found-only pack directory path..."
rm -rf "${FAKE_ROOT}/packs/kubernetes" "${FAKE_ROOT}/virtualenvs/kubernetes"
mkdir -p "${FAKE_ROOT}/packs/kubernetes/lost+found" "${FAKE_ROOT}/virtualenvs/kubernetes"
run_installer "${GIT_LOST_FOUND_PACK_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" bash
assert_contains "Installing StackStorm pack kubernetes from https://example.invalid/stackstorm-kubernetes.git" "${GIT_LOST_FOUND_PACK_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${GIT_LOST_FOUND_PACK_OUT}"
[[ -f "${FAKE_ROOT}/packs/kubernetes/pack.yaml" ]] || fail "expected pack install to ignore lost+found"

echo "Checking git lost+found-only virtualenv directory path..."
rm -rf "${FAKE_ROOT}/virtualenvs/kubernetes"
mkdir -p "${FAKE_ROOT}/virtualenvs/kubernetes/lost+found"
run_installer "${GIT_LOST_FOUND_VENV_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" bash
assert_contains "Reusing existing StackStorm pack directory ${FAKE_ROOT}/packs/kubernetes" "${GIT_LOST_FOUND_VENV_OUT}"
assert_contains "Creating StackStorm virtualenv ${FAKE_ROOT}/virtualenvs/kubernetes" "${GIT_LOST_FOUND_VENV_OUT}"
[[ -x "${FAKE_ROOT}/virtualenvs/kubernetes/bin/pip" ]] || fail "expected virtualenv creation to ignore lost+found"

echo "Checking git install with ref..."
rm -rf "${FAKE_ROOT}/packs/kubernetes" "${FAKE_ROOT}/virtualenvs/kubernetes"
run_installer "${GIT_VERSION_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" ST2_INSTALL_KUBERNETES_PACK_REPO_URL="https://example.invalid/stackstorm-kubernetes.git" ST2_INSTALL_KUBERNETES_PACK_VERSION="main" bash
assert_contains "Installing StackStorm pack kubernetes=main from https://example.invalid/stackstorm-kubernetes.git" "${GIT_VERSION_OUT}"

echo "Checking validation failure for git without repo URL..."
if run_installer "${MISSING_REPO_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="git" bash; then
  fail "expected git source without repo URL to fail"
fi
assert_contains "required value 'git repo url for kubernetes' is empty" "${MISSING_REPO_OUT}"

echo "Checking validation failure for unsupported source type..."
if run_installer "${BAD_SOURCE_OUT}" env ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE="tarball" bash; then
  fail "expected unsupported source type to fail"
fi
assert_contains "unsupported source type 'tarball' for pack kubernetes" "${BAD_SOURCE_OUT}"

echo "[PASS] Third-party StackStorm pack installer checks passed"

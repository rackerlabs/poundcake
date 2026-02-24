#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/../bin"
POUNDCAKE_INSTALLER="${BIN_DIR}/install-poundcake.sh"
BAKERY_INSTALLER="${BIN_DIR}/install-bakery.sh"
WRAPPER_SCRIPT="${SCRIPT_DIR}/../../install/install-poundcake-helm.sh"

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
    fail "unexpected content present"
  fi
}

assert_not_exists() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    fail "unexpected path exists: ${path}"
  fi
}

echo "Checking installer path rename + wrapper target dispatch..."
[[ -x "${POUNDCAKE_INSTALLER}" ]] || fail "missing ${POUNDCAKE_INSTALLER}"
[[ -x "${BAKERY_INSTALLER}" ]] || fail "missing ${BAKERY_INSTALLER}"
if find "${BIN_DIR}" -maxdepth 1 -type f -name 'install-poundcake*-env.sh' | rg -q .; then
  fail "legacy poundcake env installer path still exists under ${BIN_DIR}"
fi

assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "${ARGS[@]}"' "${WRAPPER_SCRIPT}"
assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-bakery.sh" "${ARGS[@]}"' "${WRAPPER_SCRIPT}"
assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" --enable-bakery "${ARGS[@]}"' "${WRAPPER_SCRIPT}"
assert_not_contains "--mode <full|bakery-only>" "${POUNDCAKE_INSTALLER}"
assert_not_contains "POUNDCAKE_INSTALL_MODE           (default: full; valid: full, bakery-only)" "${POUNDCAKE_INSTALLER}"

# Build mock commands so tests run without a live cluster.
TMP_DIR="$(mktemp -d)"
MOCK_BIN="${TMP_DIR}/mockbin"
mkdir -p "${MOCK_BIN}"

cat > "${MOCK_BIN}/helm" <<'HELM_EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${TEST_HELM_LOG:?missing TEST_HELM_LOG}"
printf '%s\n' "$*" >> "${TEST_HELM_LOG}"

cmd="${1:-}"
case "${cmd}" in
  template)
    cat <<'YAML_EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: poundcake-api
spec:
  template:
    spec:
      containers:
        - name: api
          readinessProbe:
            httpGet:
              path: /api/v1/ready
          livenessProbe:
            httpGet:
              path: /api/v1/live
          env:
            - name: POUNDCAKE_PACK_SYNC_ENDPOINT
              value: http://poundcake-api:8000/api/v1/cook/packs
YAML_EOF
    ;;
  lint|upgrade|registry|pull)
    ;;
  *)
    ;;
esac
HELM_EOF
chmod +x "${MOCK_BIN}/helm"

cat > "${MOCK_BIN}/kubectl" <<'KUBE_EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${TEST_KUBECTL_LOG:?missing TEST_KUBECTL_LOG}"
printf '%s\n' "$*" >> "${TEST_KUBECTL_LOG}"

if [[ "${1:-}" == "get" && "${2:-}" == "namespace" ]]; then
  exit 1
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "create" && "${4:-}" == "secret" && "${5:-}" == "generic" ]]; then
  cat <<'YAML_EOF'
apiVersion: v1
kind: Secret
metadata:
  name: mock
YAML_EOF
  exit 0
fi
exit 0
KUBE_EOF
chmod +x "${MOCK_BIN}/kubectl"

cat > "${TMP_DIR}/values.yaml" <<'VALUES_EOF'
bakery:
  database:
    createServer: true
VALUES_EOF

run_with_mocks() {
  local out_file="$1"
  shift
  TEST_HELM_LOG="${TMP_DIR}/helm.log"
  TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log"
  : > "${TEST_HELM_LOG}"
  : > "${TEST_KUBECTL_LOG}"

  PATH="${MOCK_BIN}:${PATH}" \
  TEST_HELM_LOG="${TEST_HELM_LOG}" \
  TEST_KUBECTL_LOG="${TEST_KUBECTL_LOG}" \
  "$@" > "${out_file}" 2>&1
}

echo "Validating Poundcake installer env overrides and CLI precedence..."
POUNDCAKE_OUT="${TMP_DIR}/poundcake.out"
run_with_mocks "${POUNDCAKE_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_IMAGE_TAG="env-tag" \
  POUNDCAKE_OPERATORS_MODE="verify" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight \
  --operators-mode skip \
  --set-string poundcakeImage.tag=cli-tag

assert_contains "Operator mode: skip" "${POUNDCAKE_OUT}"
assert_contains "upgrade --install env-rel" "${TMP_DIR}/helm.log"
assert_contains "--namespace env-ns" "${TMP_DIR}/helm.log"
assert_contains "--set poundcake.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set-string poundcakeImage.tag=env-tag" "${TMP_DIR}/helm.log"
assert_contains "--set-string poundcakeImage.tag=cli-tag" "${TMP_DIR}/helm.log"
assert_contains "-f ${TMP_DIR}/values.yaml --set poundcake.enabled=true" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer env overrides and standalone DB enforcement..."
BAKERY_OUT="${TMP_DIR}/bakery.out"
run_with_mocks "${BAKERY_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_BAKERY_IMAGE_REPO="example.registry.local/poundcake-bakery" \
  POUNDCAKE_BAKERY_IMAGE_TAG="env-bakery-tag" \
  POUNDCAKE_OPERATORS_MODE="verify" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --operators-mode skip

assert_contains "Operator mode: skip" "${BAKERY_OUT}"
assert_contains "upgrade --install bakery-env-rel" "${TMP_DIR}/helm.log"
assert_contains "--namespace bakery-env-ns" "${TMP_DIR}/helm.log"
assert_contains "--set poundcake.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.database.createServer=true" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.repository=example.registry.local/poundcake-bakery" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.tag=env-bakery-tag" "${TMP_DIR}/helm.log"

echo "Validating Bakery integrated DB guardrails..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_BAKERY_DB_INTEGRATED=true "${BAKERY_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected POUNDCAKE_BAKERY_DB_INTEGRATED=true to fail for bakery installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  "${BAKERY_INSTALLER}" --skip-preflight --bakery-db-integrated >/dev/null 2>&1; then
  fail "expected --bakery-db-integrated to fail for bakery installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_BAKERY_DB_HOST=shared-db "${POUNDCAKE_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected POUNDCAKE_BAKERY_DB_HOST to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  "${POUNDCAKE_INSTALLER}" --skip-preflight --bakery-db-host shared-db >/dev/null 2>&1; then
  fail "expected --bakery-db-host to fail for poundcake installer"
fi

echo "Validating legacy mode removal guardrails..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  "${POUNDCAKE_INSTALLER}" --mode full --skip-preflight >/dev/null 2>&1; then
  fail "expected --mode to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_INSTALL_MODE=full "${POUNDCAKE_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected POUNDCAKE_INSTALL_MODE to fail for poundcake installer"
fi

echo "Installer rename and env override checks passed!"

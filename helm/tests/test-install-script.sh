#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/../bin"
POUNDCAKE_INSTALLER="${BIN_DIR}/install-poundcake.sh"
BAKERY_INSTALLER="${BIN_DIR}/install-bakery.sh"
POUNDCAKE_WRAPPER="${SCRIPT_DIR}/../../install/install-poundcake-helm.sh"
BAKERY_WRAPPER="${SCRIPT_DIR}/../../install/install-bakery-helm.sh"

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

echo "Checking installer wrappers and operator source defaults..."
[[ -x "${POUNDCAKE_INSTALLER}" ]] || fail "missing ${POUNDCAKE_INSTALLER}"
[[ -x "${BAKERY_INSTALLER}" ]] || fail "missing ${BAKERY_INSTALLER}"
[[ -x "${POUNDCAKE_WRAPPER}" ]] || fail "missing ${POUNDCAKE_WRAPPER}"
[[ -x "${BAKERY_WRAPPER}" ]] || fail "missing ${BAKERY_WRAPPER}"

assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-poundcake.sh" "$@"' "${POUNDCAKE_WRAPPER}"
assert_contains 'exec "$PROJECT_ROOT/helm/bin/install-bakery.sh" "$@"' "${BAKERY_WRAPPER}"
assert_not_contains "both" "${POUNDCAKE_WRAPPER}"
assert_not_contains "case \"\${TARGET}\"" "${POUNDCAKE_WRAPPER}"

assert_contains "https://helm.mariadb.com/mariadb-operator" "${POUNDCAKE_INSTALLER}"
assert_contains "https://ot-container-kit.github.io/helm-charts" "${POUNDCAKE_INSTALLER}"
assert_contains "https://github.com/rabbitmq/cluster-operator/releases/download/v2.12.0/cluster-operator.yml" "${POUNDCAKE_INSTALLER}"
assert_contains "https://github.com/rabbitmq/messaging-topology-operator/releases/download/v1.15.0/messaging-topology-operator-with-certmanager.yaml" "${POUNDCAKE_INSTALLER}"
assert_contains "https://mongodb.github.io/helm-charts" "${POUNDCAKE_INSTALLER}"

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
              path: /api/v1/health
          livenessProbe:
            httpGet:
              path: /api/v1/health
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

if [[ "${1:-}" == "cluster-info" ]]; then
  exit 0
fi
if [[ "${1:-}" == "get" && "${2:-}" == "namespace" ]]; then
  exit 1
fi
if [[ "${1:-}" == "create" && "${2:-}" == "namespace" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "secret" ]]; then
  if [[ "${MOCK_BAKERY_SECRET_EXISTS:-1}" == "1" ]]; then
    exit 0
  fi
  exit 1
fi
if [[ "${1:-}" == "get" && "${2:-}" == "crd" ]]; then
  # Default to present so operator checks can pass in verify/skip tests.
  exit 0
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "create" && "${4:-}" == "secret" ]]; then
  cat <<'YAML_EOF'
apiVersion: v1
kind: Secret
metadata:
  name: mock
YAML_EOF
  exit 0
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "apply" && "${4:-}" == "-f" && "${5:-}" == "-" ]]; then
  cat >/dev/null
  exit 0
fi
if [[ "${1:-}" == "apply" && "${2:-}" == "-f" && "${3:-}" == "-" ]]; then
  cat >/dev/null
  exit 0
fi

# Bakery service discovery list call
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "service" && "${5:-}" == "-l" ]]; then
  case "${MOCK_BAKERY_DISCOVERY:-none}" in
    single)
      echo "bakery"
      ;;
    ambiguous)
      echo "bakery-a"
      echo "bakery-b"
      ;;
    *)
      ;;
  esac
  exit 0
fi

# Bakery deployment discovery list call
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "deployment" && "${5:-}" == "-l" ]]; then
  case "${MOCK_BAKERY_DISCOVERY:-none}" in
    single)
      echo "bakery"
      ;;
    ambiguous)
      echo "bakery-a"
      echo "bakery-b"
      ;;
    *)
      ;;
  esac
  exit 0
fi

# Individual bakery service port lookup
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "service" && "${5:-}" != "-l" ]]; then
  echo "${MOCK_BAKERY_PORT:-8000}"
  exit 0
fi

# Individual bakery deployment env lookup
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "deployment" && "${5:-}" != "-l" ]]; then
  echo "DATABASE_HOST=${MOCK_BAKERY_DB_HOST:-bakery-mariadb}"
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

echo "Validating PoundCake installer fixed deployment toggles..."
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
assert_contains "--set bakery.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.client.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set database.mode=embedded" "${TMP_DIR}/helm.log"
assert_contains "--set-string poundcakeImage.tag=env-tag" "${TMP_DIR}/helm.log"
assert_contains "--set-string poundcakeImage.tag=cli-tag" "${TMP_DIR}/helm.log"

echo "Validating PoundCake Bakery/DB auto-discovery..."
DISCOVERY_OUT="${TMP_DIR}/poundcake-discovery.out"
run_with_mocks "${DISCOVERY_OUT}" \
  env \
  MOCK_BAKERY_DISCOVERY="single" \
  MOCK_BAKERY_DB_HOST="bakery-shared-mariadb" \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_IMAGE_TAG="env-tag" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight

assert_contains "--set bakery.client.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.client.baseUrl=http://bakery.env-ns.svc.cluster.local:8000" "${TMP_DIR}/helm.log"
assert_contains "--set database.mode=shared_operator" "${TMP_DIR}/helm.log"
assert_contains "--set-string database.sharedOperator.serverName=bakery-shared-mariadb" "${TMP_DIR}/helm.log"

echo "Validating explicit remote Bakery URL precedence over auto-discovery..."
EXPLICIT_REMOTE_OUT="${TMP_DIR}/poundcake-remote.out"
run_with_mocks "${EXPLICIT_REMOTE_OUT}" \
  env \
  MOCK_BAKERY_DISCOVERY="single" \
  MOCK_BAKERY_DB_HOST="bakery-shared-mariadb" \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_IMAGE_TAG="env-tag" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight \
  --remote-bakery-url https://bakery.external.example

assert_contains "--set-string bakery.client.baseUrl=https://bakery.external.example" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.client.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set database.mode=embedded" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer fixed toggles and profile..."
BAKERY_OUT="${TMP_DIR}/bakery.out"
run_with_mocks "${BAKERY_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_BAKERY_IMAGE_REPO="example.registry.local/poundcake-bakery" \
  POUNDCAKE_BAKERY_IMAGE_TAG="env-bakery-tag" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight

assert_contains "Installer profile: bakery" "${BAKERY_OUT}"
assert_contains "upgrade --install bakery-env-rel" "${TMP_DIR}/helm.log"
assert_contains "--set poundcake.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.worker.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.database.createServer=true" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.repository=example.registry.local/poundcake-bakery" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.tag=env-bakery-tag" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.digest=" "${TMP_DIR}/helm.log"

echo "Validating Bakery digest precedence over tag..."
BAKERY_DIGEST_OUT="${TMP_DIR}/bakery-digest.out"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_BAKERY_IMAGE_REPO="example.registry.local/poundcake-bakery" \
  POUNDCAKE_BAKERY_IMAGE_TAG="env-bakery-tag" \
  POUNDCAKE_BAKERY_IMAGE_DIGEST="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight >"${BAKERY_DIGEST_OUT}" 2>&1; then
  fail "expected bakery digest+tag conflict to fail"
fi
assert_contains "Set only one of POUNDCAKE_BAKERY_IMAGE_TAG or POUNDCAKE_BAKERY_IMAGE_DIGEST." "${BAKERY_DIGEST_OUT}"

echo "Validating global digest fallback for Bakery image..."
BAKERY_GLOBAL_DIGEST_OUT="${TMP_DIR}/bakery-global-digest.out"
run_with_mocks "${BAKERY_GLOBAL_DIGEST_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_IMAGE_DIGEST="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight

assert_contains "--set-string bakery.image.digest=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.image.tag=" "${TMP_DIR}/helm.log"

echo "Validating Bakery digest overrides global digest..."
BAKERY_BOTH_DIGESTS_OUT="${TMP_DIR}/bakery-both-digests.out"
run_with_mocks "${BAKERY_BOTH_DIGESTS_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_IMAGE_DIGEST="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
  POUNDCAKE_BAKERY_IMAGE_DIGEST="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight

assert_contains "--set-string bakery.image.digest=sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.digest=sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer with no forwarded args..."
BAKERY_NOARGS_OUT="${TMP_DIR}/bakery-noargs.out"
run_with_mocks "${BAKERY_NOARGS_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}"

assert_contains "Installer profile: bakery" "${BAKERY_NOARGS_OUT}"
assert_contains "--set poundcake.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.worker.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.database.createServer=true" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer secret creation when missing..."
BAKERY_SECRET_CREATE_OUT="${TMP_DIR}/bakery-secret-create.out"
run_with_mocks "${BAKERY_SECRET_CREATE_OUT}" \
  env \
  MOCK_BAKERY_SECRET_EXISTS=0 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_BAKERY_IMAGE_REPO="example.registry.local/poundcake-bakery" \
  POUNDCAKE_BAKERY_IMAGE_TAG="env-bakery-tag" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --bakery-rackspace-url https://example.core.local \
  --bakery-rackspace-username bakery-user \
  --bakery-rackspace-password bakery-pass

assert_contains "create secret generic bakery-rackspace-core" "${TMP_DIR}/kubectl.log"
assert_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer requires --update-bakery-secret for credential changes..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env MOCK_BAKERY_SECRET_EXISTS=1 POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=false \
  "${BAKERY_INSTALLER}" --skip-preflight --bakery-rackspace-password rotate-me >/dev/null 2>&1; then
  fail "expected bakery secret update without --update-bakery-secret to fail"
fi

echo "Validating ambiguous discovery guardrail..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env MOCK_BAKERY_DISCOVERY=ambiguous POUNDCAKE_IMAGE_TAG=env-tag POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected ambiguous Bakery discovery to fail"
fi

echo "Validating removed mixed-mode guardrails..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_IMAGE_TAG=env-tag POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight --enable-bakery >/dev/null 2>&1; then
  fail "expected --enable-bakery to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_IMAGE_TAG=env-tag POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight --mode full >/dev/null 2>&1; then
  fail "expected --mode to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  env POUNDCAKE_INSTALL_MODE=full POUNDCAKE_IMAGE_TAG=env-tag POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected POUNDCAKE_INSTALL_MODE to fail for poundcake installer"
fi

echo "Installer checks passed."

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
    echo "--- file contents ---" >&2
    cat "${file}" >&2 || true
    echo "---------------------" >&2
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

TMP_DIR="$(mktemp -d)"
MOCK_BIN="${TMP_DIR}/mockbin"
mkdir -p "${MOCK_BIN}"

cat > "${MOCK_BIN}/helm" <<'HELM_EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${TEST_HELM_LOG:?missing TEST_HELM_LOG}"
printf '%s\n' "$*" >> "${TEST_HELM_LOG}"

case "${1:-}" in
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
: "${TEST_KUBECTL_CREATED_SECRETS:?missing TEST_KUBECTL_CREATED_SECRETS}"
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
if [[ "${1:-}" == "get" && "${2:-}" == "crd" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "get" && "${4:-}" == "secret" ]]; then
  secret_name="${5:-}"
  if [[ -f "${TEST_KUBECTL_CREATED_SECRETS}" ]] && rg -Fxq -- "${secret_name}" "${TEST_KUBECTL_CREATED_SECRETS}"; then
    exit 0
  fi
  case "${secret_name}" in
    bakery-rackspace-core)
      secret_exists="${MOCK_BAKERY_RACKSPACE_SECRET_EXISTS:-${MOCK_BAKERY_SECRET_EXISTS:-1}}"
      ;;
    bakery-servicenow)
      secret_exists="${MOCK_BAKERY_SERVICENOW_SECRET_EXISTS:-0}"
      ;;
    bakery-jira)
      secret_exists="${MOCK_BAKERY_JIRA_SECRET_EXISTS:-0}"
      ;;
    bakery-github)
      secret_exists="${MOCK_BAKERY_GITHUB_SECRET_EXISTS:-0}"
      ;;
    bakery-pagerduty)
      secret_exists="${MOCK_BAKERY_PAGERDUTY_SECRET_EXISTS:-0}"
      ;;
    bakery-teams)
      secret_exists="${MOCK_BAKERY_TEAMS_SECRET_EXISTS:-0}"
      ;;
    bakery-discord)
      secret_exists="${MOCK_BAKERY_DISCORD_SECRET_EXISTS:-0}"
      ;;
    *)
      secret_exists="${MOCK_BAKERY_SECRET_EXISTS:-1}"
      ;;
  esac
  if [[ "${secret_exists}" == "1" ]]; then
    exit 0
  fi
  exit 1
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "create" && "${4:-}" == "secret" ]]; then
  secret_name="${6:-mock}"
  printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n' "${secret_name}"
  exit 0
fi
if [[ "${1:-}" == "-n" && "${3:-}" == "apply" && "${4:-}" == "-f" && "${5:-}" == "-" ]]; then
  manifest="$(cat)"
  secret_name="$(printf '%s\n' "${manifest}" | awk '/^  name:/ { print $2; exit }')"
  if [[ -n "${secret_name}" ]]; then
    printf '%s\n' "${secret_name}" >> "${TEST_KUBECTL_CREATED_SECRETS}"
  fi
  exit 0
fi
if [[ "${1:-}" == "apply" && "${2:-}" == "-f" && "${3:-}" == "-" ]]; then
  manifest="$(cat)"
  secret_name="$(printf '%s\n' "${manifest}" | awk '/^  name:/ { print $2; exit }')"
  if [[ -n "${secret_name}" ]]; then
    printf '%s\n' "${secret_name}" >> "${TEST_KUBECTL_CREATED_SECRETS}"
  fi
  exit 0
fi

exit 0
KUBE_EOF
chmod +x "${MOCK_BIN}/kubectl"

cat > "${TMP_DIR}/values.yaml" <<'VALUES_EOF'
bakery:
  database:
    createServer: true
  image:
    repository: example.registry.local/poundcake-bakery
    tag: values-bakery-tag
  client:
    enabled: false
poundcakeImage:
  repository: example.registry.local/poundcake
  tag: values-pc-tag
uiImage:
  repository: example.registry.local/poundcake-ui
  tag: values-ui-tag
stackstormImage:
  repository: example.registry.local/stackstorm
  tag: "3.9.0"
VALUES_EOF

run_with_mocks() {
  local out_file="$1"
  shift
  TEST_HELM_LOG="${TMP_DIR}/helm.log"
  TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log"
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log"
  : > "${TEST_HELM_LOG}"
  : > "${TEST_KUBECTL_LOG}"
  : > "${TEST_KUBECTL_CREATED_SECRETS}"

  PATH="${MOCK_BIN}:${PATH}" \
  TEST_HELM_LOG="${TEST_HELM_LOG}" \
  TEST_KUBECTL_LOG="${TEST_KUBECTL_LOG}" \
  TEST_KUBECTL_CREATED_SECRETS="${TEST_KUBECTL_CREATED_SECRETS}" \
  "$@" > "${out_file}" 2>&1
}

echo "Validating PoundCake installer fixed deployment toggles..."
POUNDCAKE_OUT="${TMP_DIR}/poundcake.out"
run_with_mocks "${POUNDCAKE_OUT}" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_OPERATORS_MODE="verify" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight \
  --operators-mode skip

assert_contains "Operator mode: skip" "${POUNDCAKE_OUT}"
assert_contains "upgrade --install env-rel" "${TMP_DIR}/helm.log"
assert_contains "--namespace env-ns" "${TMP_DIR}/helm.log"
assert_contains "--set poundcake.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.worker.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "-f ${TMP_DIR}/values.yaml" "${TMP_DIR}/helm.log"
assert_not_contains "bakery.client.enabled" "${TMP_DIR}/helm.log"
assert_not_contains "database.mode=" "${TMP_DIR}/helm.log"
assert_not_contains "stackstormPackSync.endpoint" "${TMP_DIR}/helm.log"
assert_not_contains "poundcakeImage.pullSecrets" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string poundcakeImage.repository=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string poundcakeImage.tag=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string uiImage.repository=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string uiImage.tag=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.repository=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.tag=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string stackstormImage.repository=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string stackstormImage.tag=" "${TMP_DIR}/helm.log"

echo "Validating PoundCake installer can create the pull secret without wiring Helm values..."
POUNDCAKE_PULL_SECRET_OUT="${TMP_DIR}/poundcake-pull-secret.out"
run_with_mocks "${POUNDCAKE_PULL_SECRET_OUT}" \
  env \
  HELM_REGISTRY_USERNAME="gh-user" \
  HELM_REGISTRY_PASSWORD="gh-pass" \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="true" \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight

assert_contains "create secret docker-registry ghcr-creds" "${TMP_DIR}/kubectl.log"
assert_not_contains "poundcakeImage.pullSecrets" "${TMP_DIR}/helm.log"

echo "Validating PoundCake installer rejects removed runtime envs..."
POUNDCAKE_REMOTE_ENV_OUT="${TMP_DIR}/poundcake-remote-env.out"
: > "${TMP_DIR}/helm.log"
: > "${TMP_DIR}/kubectl.log"
: > "${TMP_DIR}/kubectl-created-secrets.log"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_REMOTE_BAKERY_URL="https://bakery.example.com" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight >"${POUNDCAKE_REMOTE_ENV_OUT}" 2>&1; then
  fail "expected removed runtime env to fail"
fi
assert_contains "POUNDCAKE_REMOTE_BAKERY_URL is no longer supported by install-poundcake.sh." "${POUNDCAKE_REMOTE_ENV_OUT}"

echo "Validating PoundCake installer rejects removed runtime flags..."
POUNDCAKE_REMOTE_FLAG_OUT="${TMP_DIR}/poundcake-remote-flag.out"
: > "${TMP_DIR}/helm.log"
: > "${TMP_DIR}/kubectl.log"
: > "${TMP_DIR}/kubectl-created-secrets.log"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight \
  --remote-bakery-url https://bakery.example.com >"${POUNDCAKE_REMOTE_FLAG_OUT}" 2>&1; then
  fail "expected removed runtime flag to fail"
fi
assert_contains "Configure remote Bakery and shared DB settings in values files or override files instead." "${POUNDCAKE_REMOTE_FLAG_OUT}"

echo "Validating PoundCake installer rejects removed pull-secret injection env..."
POUNDCAKE_PULL_SECRET_ENV_OUT="${TMP_DIR}/poundcake-pull-secret-env.out"
: > "${TMP_DIR}/helm.log"
: > "${TMP_DIR}/kubectl.log"
: > "${TMP_DIR}/kubectl-created-secrets.log"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight >"${POUNDCAKE_PULL_SECRET_ENV_OUT}" 2>&1; then
  fail "expected removed pull-secret env to fail"
fi
assert_contains "POUNDCAKE_IMAGE_PULL_SECRET_ENABLED is no longer supported by install-poundcake.sh." "${POUNDCAKE_PULL_SECRET_ENV_OUT}"

echo "Validating Bakery installer fixed toggles and default secret-name behavior..."
BAKERY_OUT="${TMP_DIR}/bakery.out"
run_with_mocks "${BAKERY_OUT}" \
  env \
  MOCK_BAKERY_RACKSPACE_SECRET_EXISTS=1 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight

assert_contains "Installer profile: bakery" "${BAKERY_OUT}"
assert_contains "upgrade --install bakery-env-rel" "${TMP_DIR}/helm.log"
assert_contains "--set poundcake.enabled=false" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.worker.enabled=true" "${TMP_DIR}/helm.log"
assert_contains "--set bakery.database.createServer=true" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.auth.existingSecret=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.client.auth.existingSecret=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.repository=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.tag=" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.image.digest=" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer secret creation when missing..."
BAKERY_SECRET_CREATE_OUT="${TMP_DIR}/bakery-secret-create.out"
run_with_mocks "${BAKERY_SECRET_CREATE_OUT}" \
  env \
  MOCK_BAKERY_SECRET_EXISTS=0 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --bakery-rackspace-url https://example.core.local \
  --bakery-rackspace-username bakery-user \
  --bakery-rackspace-password bakery-pass

assert_contains "create secret generic bakery-rackspace-core" "${TMP_DIR}/kubectl.log"
assert_not_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer forwards custom provider secret names only when needed..."
BAKERY_CUSTOM_SECRET_OUT="${TMP_DIR}/bakery-custom-secret.out"
run_with_mocks "${BAKERY_CUSTOM_SECRET_OUT}" \
  env \
  MOCK_BAKERY_SECRET_EXISTS=0 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --bakery-rackspace-secret-name custom-core \
  --bakery-rackspace-url https://example.core.local \
  --bakery-rackspace-username bakery-user \
  --bakery-rackspace-password bakery-pass

assert_contains "create secret generic custom-core" "${TMP_DIR}/kubectl.log"
assert_contains "--set-string bakery.rackspaceCore.existingSecret=custom-core" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer forwards custom auth secret names only when needed..."
BAKERY_CUSTOM_AUTH_OUT="${TMP_DIR}/bakery-custom-auth.out"
run_with_mocks "${BAKERY_CUSTOM_AUTH_OUT}" \
  env \
  MOCK_BAKERY_SECRET_EXISTS=0 \
  MOCK_BAKERY_RACKSPACE_SECRET_EXISTS=1 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --bakery-auth-secret-name custom-bakery-auth

assert_contains "create secret generic custom-bakery-auth" "${TMP_DIR}/kubectl.log"
assert_contains "--set-string bakery.auth.existingSecret=custom-bakery-auth" "${TMP_DIR}/helm.log"
assert_contains "--set-string bakery.client.auth.existingSecret=custom-bakery-auth" "${TMP_DIR}/helm.log"

echo "Validating Teams-only Bakery installs do not force Rackspace secret wiring..."
BAKERY_TEAMS_ONLY_OUT="${TMP_DIR}/bakery-teams-only.out"
run_with_mocks "${BAKERY_TEAMS_ONLY_OUT}" \
  env \
  MOCK_BAKERY_RACKSPACE_SECRET_EXISTS=0 \
  MOCK_BAKERY_TEAMS_SECRET_EXISTS=0 \
  POUNDCAKE_NAMESPACE="bakery-env-ns" \
  POUNDCAKE_RELEASE_NAME="bakery-env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET="false" \
  "${BAKERY_INSTALLER}" \
  --skip-preflight \
  --bakery-active-provider teams \
  --bakery-teams-webhook-url https://teams.example/webhook

assert_contains "create secret generic bakery-teams" "${TMP_DIR}/kubectl.log"
assert_contains "--set-string bakery.config.activeProvider=teams" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.teams.existingSecret=bakery-teams" "${TMP_DIR}/helm.log"
assert_not_contains "--set-string bakery.rackspaceCore.existingSecret=bakery-rackspace-core" "${TMP_DIR}/helm.log"

echo "Validating Bakery installer requires --update-bakery-secret for credential changes..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env MOCK_BAKERY_SECRET_EXISTS=1 POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${BAKERY_INSTALLER}" --skip-preflight --bakery-rackspace-password rotate-me >/dev/null 2>&1; then
  fail "expected bakery secret update without --update-bakery-secret to fail"
fi

echo "Validating PoundCake installer rejects image environment variables..."
POUNDCAKE_IMAGE_ENV_OUT="${TMP_DIR}/poundcake-image-env.out"
: > "${TMP_DIR}/helm.log"
: > "${TMP_DIR}/kubectl.log"
: > "${TMP_DIR}/kubectl-created-secrets.log"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_IMAGE_TAG="env-tag" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight >"${POUNDCAKE_IMAGE_ENV_OUT}" 2>&1; then
  fail "expected image environment variable usage to fail"
fi
assert_contains "Image environment variables are no longer supported by the Helm installers: POUNDCAKE_IMAGE_TAG" "${POUNDCAKE_IMAGE_ENV_OUT}"

echo "Validating PoundCake installer rejects image --set overrides..."
POUNDCAKE_IMAGE_SET_OUT="${TMP_DIR}/poundcake-image-set.out"
: > "${TMP_DIR}/helm.log"
: > "${TMP_DIR}/kubectl.log"
: > "${TMP_DIR}/kubectl-created-secrets.log"
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env \
  POUNDCAKE_NAMESPACE="env-ns" \
  POUNDCAKE_RELEASE_NAME="env-rel" \
  POUNDCAKE_OPERATORS_MODE="skip" \
  POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" \
  POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" \
  --skip-preflight \
  --set-string poundcakeImage.tag=cli-tag >"${POUNDCAKE_IMAGE_SET_OUT}" 2>&1; then
  fail "expected image --set override usage to fail"
fi
assert_contains "Image --set overrides are not supported by the Helm installers." "${POUNDCAKE_IMAGE_SET_OUT}"

echo "Validating removed mixed-mode guardrails..."
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight --enable-bakery >/dev/null 2>&1; then
  fail "expected --enable-bakery to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight --mode full >/dev/null 2>&1; then
  fail "expected --mode to fail for poundcake installer"
fi
if PATH="${MOCK_BIN}:${PATH}" TEST_HELM_LOG="${TMP_DIR}/helm.log" TEST_KUBECTL_LOG="${TMP_DIR}/kubectl.log" \
  TEST_KUBECTL_CREATED_SECRETS="${TMP_DIR}/kubectl-created-secrets.log" \
  env POUNDCAKE_INSTALL_MODE=full POUNDCAKE_OPERATORS_MODE=skip POUNDCAKE_BASE_OVERRIDES="${TMP_DIR}/values.yaml" POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
  "${POUNDCAKE_INSTALLER}" --skip-preflight >/dev/null 2>&1; then
  fail "expected POUNDCAKE_INSTALL_MODE to fail for poundcake installer"
fi

echo "Installer checks passed."

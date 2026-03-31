#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_E2E="${SCRIPT_DIR}/run_e2e.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  if [[ "${haystack}" != *"${needle}"* ]]; then
    echo "FAIL: ${label}" >&2
    echo "Expected to find: ${needle}" >&2
    echo "Output was:" >&2
    echo "${haystack}" >&2
    exit 1
  fi
}

run_expect_success() {
  local label="$1"
  shift
  local output
  if ! output="$("$@" 2>&1)"; then
    echo "FAIL: ${label}" >&2
    echo "${output}" >&2
    exit 1
  fi
  echo "${output}"
}

run_expect_failure() {
  local label="$1"
  shift
  local output
  if output="$("$@" 2>&1)"; then
    echo "FAIL: ${label} (expected failure)" >&2
    echo "${output}" >&2
    exit 1
  fi
  echo "${output}"
}

make_temp_runner() {
  local runner
  runner="$(mktemp "${TMPDIR:-/tmp}/poundcake-e2e-runner.XXXXXX")"
  cat >"${runner}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
  chmod +x "${runner}"
  echo "${runner}"
}

make_mock_curl_dir() {
  local dir
  dir="$(mktemp -d "${TMPDIR:-/tmp}/poundcake-mock-curl.XXXXXX")"
  cat >"${dir}/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

url=""
header=""
cookie=""
while [ $# -gt 0 ]; do
  case "$1" in
    -H)
      header="${2:-}"
      shift 2
      ;;
    --cookie)
      cookie="${2:-}"
      shift 2
      ;;
    -w|-o|-m|-X|-d)
      shift 2
      ;;
    -s|-S|-sS)
      shift
      ;;
    http://*|https://*)
      url="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

case "${url}" in
  */api/v1/settings)
    if [ "${MOCK_AUTH_ENABLED:-false}" = "true" ]; then
      if [ -n "${EXPECTED_SERVICE_TOKEN:-}" ] && [ "${header}" = "X-Auth-Token: ${EXPECTED_SERVICE_TOKEN}" ]; then
        printf '{"auth_enabled":true}\n200\n'
        exit 0
      fi
      if [ -n "${EXPECTED_SESSION_TOKEN:-}" ] && [ "${cookie}" = "session_token=${EXPECTED_SESSION_TOKEN}" ]; then
        printf '{"auth_enabled":true}\n200\n'
        exit 0
      fi
      printf '{"detail":"Not authenticated"}\n401\n'
      exit 0
    fi
    printf '{"auth_enabled":false}\n200\n'
    exit 0
    ;;
  */api/v1/health)
    printf '\n200\n'
    exit 0
    ;;
esac

printf '{"detail":"Unhandled URL"}\n500\n'
EOF
  chmod +x "${dir}/curl"
  echo "${dir}"
}

output="$(run_expect_success "compose default URL" env DEBUG=1 "${RUN_E2E}" --list)"
assert_contains "${output}" "Resolved poundcake_api URL: http://localhost:8000/api/v1" "compose default URL"

output="$(run_expect_failure "k8s requires explicit service" env DEBUG=1 TEST_TARGET=k8s "${RUN_E2E}" --list)"
assert_contains "${output}" "--target k8s requires --service unless --api-url is provided" "k8s requires explicit service"

output="$(run_expect_success "k8s explicit service FQDN URL" env DEBUG=1 "${RUN_E2E}" --target k8s --service poundcake-api --namespace rackspace --remote-port 8000 --list)"
assert_contains "${output}" "Resolved poundcake_api URL: http://poundcake-api.rackspace.svc.cluster.local:8000/api/v1" "k8s explicit service FQDN URL"

output="$(run_expect_success "k8s port-forward uses localhost URL" env DEBUG=1 "${RUN_E2E}" --target k8s --service poundcake-api --namespace rackspace --enable-port-forward --local-port 18000 --list)"
assert_contains "${output}" "Resolved poundcake_api URL: http://localhost:18000/api/v1" "k8s port-forward uses localhost URL"

output="$(run_expect_success "api-url override wins" env DEBUG=1 "${RUN_E2E}" --target k8s --service poundcake-api --api-url http://example:9999/api/v1 --list)"
assert_contains "${output}" "Resolved poundcake_api URL: http://example:9999/api/v1" "api-url override wins"

output="$(run_expect_failure "api-rul typo guidance" env DEBUG=1 "${RUN_E2E}" --api-rul http://x --list)"
assert_contains "${output}" "Unknown argument --api-rul; did you mean --api-url?" "api-rul typo guidance"

runner="$(make_temp_runner)"
mock_curl_dir="$(make_mock_curl_dir)"
trap 'rm -f "${runner}"; rm -rf "${mock_curl_dir}"' EXIT

output="$(run_expect_success \
  "auth disabled proceeds without credentials" \
  env PATH="${mock_curl_dir}:$PATH" MOCK_AUTH_ENABLED=false DEBUG=1 "${RUN_E2E}" --single "${runner}")"
assert_contains "${output}" "Running single e2e runner" "auth disabled proceeds without credentials"

output="$(run_expect_failure \
  "auth enabled missing credentials fails fast" \
  env PATH="${mock_curl_dir}:$PATH" MOCK_AUTH_ENABLED=true DEBUG=1 "${RUN_E2E}" --single "${runner}")"
assert_contains "${output}" "Auth appears to be enabled" "auth enabled missing credentials fails fast"

output="$(run_expect_success \
  "auth enabled service token proceeds" \
  env PATH="${mock_curl_dir}:$PATH" MOCK_AUTH_ENABLED=true EXPECTED_SERVICE_TOKEN=shared-internal-key \
    POUNDCAKE_AUTH_SERVICE_TOKEN=shared-internal-key DEBUG=1 "${RUN_E2E}" --single "${runner}")"
assert_contains "${output}" "Auth preflight passed using service-token auth" "auth enabled service token proceeds"

output="$(run_expect_success \
  "auth enabled session token proceeds" \
  env PATH="${mock_curl_dir}:$PATH" MOCK_AUTH_ENABLED=true EXPECTED_SESSION_TOKEN=session-123 \
    POUNDCAKE_SESSION_TOKEN=session-123 DEBUG=1 "${RUN_E2E}" --single "${runner}")"
assert_contains "${output}" "Auth preflight passed using session-cookie auth" "auth enabled session token proceeds"

echo "run_e2e API_URL resolution tests passed."

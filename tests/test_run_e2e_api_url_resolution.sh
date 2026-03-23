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

echo "run_e2e API_URL resolution tests passed."

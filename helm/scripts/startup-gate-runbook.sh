#!/usr/bin/env bash
set -euo pipefail

# Collect deterministic startup-gate diagnostics for PoundCake API init delays.
NAMESPACE="${1:-poundcake}"
API_POD="${2:-}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command '$1' not found" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd awk
require_cmd sed
require_cmd grep
require_cmd date

if [ -z "$API_POD" ]; then
  API_POD="$(kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
fi

if [ -z "$API_POD" ]; then
  echo "ERROR: unable to discover poundcake-api pod in namespace '$NAMESPACE'" >&2
  echo "Usage: $0 <namespace> [api-pod-name]" >&2
  exit 1
fi

START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUTDIR="/tmp/poundcake-startup-gate-${NAMESPACE}-${API_POD}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"

echo "Collecting startup gate diagnostics"
echo "  namespace: $NAMESPACE"
echo "  api pod:    $API_POD"
echo "  out dir:    $OUTDIR"

decode_or_empty() {
  local path="$1"
  local secret="$2"
  local value
  value="$(kubectl -n "$NAMESPACE" get secret "$secret" -o "jsonpath=${path}" 2>/dev/null || true)"
  if [ -n "$value" ]; then
    printf '%s' "$value" | base64 -d 2>/dev/null || true
  fi
}

extract_gate_first() {
  local gate="$1"
  awk -v gate="$gate" '$0 ~ gate { print $1; exit }' "$OUTDIR/wait-stage-ready.log"
}

extract_gate_last() {
  local gate="$1"
  awk -v gate="$gate" '$0 ~ gate { ts=$1 } END { if (ts != "") print ts }' "$OUTDIR/wait-stage-ready.log"
}

extract_job_meta() {
  local job="$1"
  local jsonpath="$2"
  kubectl -n "$NAMESPACE" get job "$job" -o "jsonpath=${jsonpath}" 2>/dev/null || true
}

to_epoch() {
  local ts="$1"
  if [ -z "$ts" ]; then
    return 0
  fi
  # GNU date
  if date -u -d "$ts" +%s >/dev/null 2>&1; then
    date -u -d "$ts" +%s
    return 0
  fi
  # BSD date
  if date -u -j -f "%Y-%m-%dT%H:%M:%S%z" "${ts/Z/+0000}" +%s >/dev/null 2>&1; then
    date -u -j -f "%Y-%m-%dT%H:%M:%S%z" "${ts/Z/+0000}" +%s
    return 0
  fi
  return 0
}

# 1) Capture gate logs with timestamps.
kubectl -n "$NAMESPACE" logs "$API_POD" -c wait-stage-ready --tail=300 --timestamps > "$OUTDIR/wait-stage-ready.log" 2>&1 || true

# 2) Snapshot markers and api key length.
POUND_MARIADB_READY="$(decode_or_empty '{.data.poundcake_mariadb_ready}' stackstorm-startup-markers)"
STACKSTORM_BOOTSTRAP_READY="$(decode_or_empty '{.data.stackstorm_bootstrap_ready}' stackstorm-startup-markers)"
ST2_KEY_LEN="$(decode_or_empty '{.data.st2_api_key}' stackstorm-apikeys | wc -c | tr -d ' ')"

# 3) Correlate job timing.
kubectl -n "$NAMESPACE" get jobs -o wide > "$OUTDIR/jobs-wide.txt" 2>&1 || true
kubectl -n "$NAMESPACE" describe job poundcake-mariadb-ready > "$OUTDIR/job-poundcake-mariadb-ready.describe.txt" 2>&1 || true
kubectl -n "$NAMESPACE" logs job/poundcake-mariadb-ready --all-containers=true > "$OUTDIR/job-poundcake-mariadb-ready.logs.txt" 2>&1 || true

# 4) Endpoint status.
kubectl -n "$NAMESPACE" get endpoints poundcake-mariadb -o yaml > "$OUTDIR/poundcake-mariadb.endpoints.yaml" 2>&1 || true

# Extract key timestamps from log and jobs.
MARIADB_GATE_FIRST="$(extract_gate_first 'wait-stage-ready-mariadb')"
MARIADB_GATE_LAST="$(extract_gate_last 'wait-stage-ready-mariadb')"
BOOTSTRAP_GATE_FIRST="$(extract_gate_first 'wait-stage-ready-stackstorm-bootstrap')"
BOOTSTRAP_GATE_LAST="$(extract_gate_last 'wait-stage-ready-stackstorm-bootstrap')"
APIKEY_GATE_FIRST="$(extract_gate_first 'wait-stage-ready-st2-apikey')"
APIKEY_GATE_LAST="$(extract_gate_last 'wait-stage-ready-st2-apikey')"

MARKERS_RESET_CREATE="$(extract_job_meta stackstorm-startup-markers-reset '{.metadata.creationTimestamp}')"
STACKSTORM_BOOTSTRAP_COMPLETE="$(extract_job_meta stackstorm-bootstrap '{.status.completionTime}')"
MARIADB_JOB_CREATE="$(extract_job_meta poundcake-mariadb-ready '{.metadata.creationTimestamp}')"
MARIADB_JOB_START="$(extract_job_meta poundcake-mariadb-ready '{.status.startTime}')"
MARIADB_JOB_COMPLETE="$(extract_job_meta poundcake-mariadb-ready '{.status.completionTime}')"
API_POD_START="$(kubectl -n "$NAMESPACE" get pod "$API_POD" -o jsonpath='{.status.startTime}' 2>/dev/null || true)"
API_CONTAINER_START="$(kubectl -n "$NAMESPACE" get pod "$API_POD" -o jsonpath='{.status.containerStatuses[0].state.running.startedAt}' 2>/dev/null || true)"

MARIADB_GATE_FIRST_EPOCH="$(to_epoch "$MARIADB_GATE_FIRST")"
MARIADB_JOB_CREATE_EPOCH="$(to_epoch "$MARIADB_JOB_CREATE")"
MARIADB_JOB_START_EPOCH="$(to_epoch "$MARIADB_JOB_START")"
MARIADB_JOB_COMPLETE_EPOCH="$(to_epoch "$MARIADB_JOB_COMPLETE")"

JOB_CREATE_LAG=0
JOB_RUNTIME=0
if [ -n "$MARIADB_GATE_FIRST_EPOCH" ] && [ -n "$MARIADB_JOB_CREATE_EPOCH" ] && [ "$MARIADB_JOB_CREATE_EPOCH" -gt "$MARIADB_GATE_FIRST_EPOCH" ]; then
  JOB_CREATE_LAG=$((MARIADB_JOB_CREATE_EPOCH - MARIADB_GATE_FIRST_EPOCH))
fi
if [ -n "$MARIADB_JOB_START_EPOCH" ] && [ -n "$MARIADB_JOB_COMPLETE_EPOCH" ] && [ "$MARIADB_JOB_COMPLETE_EPOCH" -ge "$MARIADB_JOB_START_EPOCH" ]; then
  JOB_RUNTIME=$((MARIADB_JOB_COMPLETE_EPOCH - MARIADB_JOB_START_EPOCH))
fi

CLASSIFICATION="undetermined"
if [ -n "$MARIADB_JOB_COMPLETE" ] && [ "$POUND_MARIADB_READY" != "true" ]; then
  CLASSIFICATION="marker patch failure"
elif [ "$JOB_CREATE_LAG" -gt 30 ] && [ "$JOB_RUNTIME" -le 30 ]; then
  CLASSIFICATION="hook sequencing latency"
elif [ "$JOB_RUNTIME" -gt 30 ]; then
  CLASSIFICATION="mariadb endpoint readiness latency"
fi

# Fallback rule using endpoint evidence for mariadb readiness latency.
if [ "$CLASSIFICATION" = "undetermined" ]; then
  if ! grep -q 'addresses:' "$OUTDIR/poundcake-mariadb.endpoints.yaml" 2>/dev/null; then
    CLASSIFICATION="mariadb endpoint readiness latency"
  fi
fi

cat > "$OUTDIR/summary.txt" <<SUMMARY
Start timestamp (UTC): $START_TS
Namespace: $NAMESPACE
API pod: $API_POD

Marker snapshot:
- poundcake_mariadb_ready: ${POUND_MARIADB_READY:-<empty>}
- stackstorm_bootstrap_ready: ${STACKSTORM_BOOTSTRAP_READY:-<empty>}
- st2_api_key bytes: ${ST2_KEY_LEN:-0}

Gate windows (from init logs):
- wait-stage-ready-mariadb: first=${MARIADB_GATE_FIRST:-N/A} last=${MARIADB_GATE_LAST:-N/A}
- wait-stage-ready-stackstorm-bootstrap: first=${BOOTSTRAP_GATE_FIRST:-N/A} last=${BOOTSTRAP_GATE_LAST:-N/A}
- wait-stage-ready-st2-apikey: first=${APIKEY_GATE_FIRST:-N/A} last=${APIKEY_GATE_LAST:-N/A}

Hook/job timing:
- stackstorm-startup-markers-reset creation: ${MARKERS_RESET_CREATE:-N/A}
- stackstorm-bootstrap completion: ${STACKSTORM_BOOTSTRAP_COMPLETE:-N/A}
- poundcake-mariadb-ready creation: ${MARIADB_JOB_CREATE:-N/A}
- poundcake-mariadb-ready start: ${MARIADB_JOB_START:-N/A}
- poundcake-mariadb-ready completion: ${MARIADB_JOB_COMPLETE:-N/A}
- poundcake-mariadb-ready create lag after mariadb gate starts: ${JOB_CREATE_LAG}s
- poundcake-mariadb-ready runtime: ${JOB_RUNTIME}s
- api pod startTime: ${API_POD_START:-N/A}
- api container startedAt: ${API_CONTAINER_START:-N/A}

Classification: $CLASSIFICATION

Timeline Table:
| Event | Observed time | Source |
|---|---|---|
| markers reset job created | ${MARKERS_RESET_CREATE:-N/A} | job/stackstorm-startup-markers-reset |
| stackstorm_bootstrap_ready=true (proxy: stackstorm-bootstrap completion) | ${STACKSTORM_BOOTSTRAP_COMPLETE:-N/A} | job/stackstorm-bootstrap |
| poundcake-mariadb-ready created | ${MARIADB_JOB_CREATE:-N/A} | job/poundcake-mariadb-ready |
| poundcake-mariadb-ready complete | ${MARIADB_JOB_COMPLETE:-N/A} | job/poundcake-mariadb-ready |
| poundcake_mariadb_ready=true (observed at gate ready) | ${MARIADB_GATE_LAST:-N/A} | pod/${API_POD} init wait-stage-ready |
| api container start | ${API_CONTAINER_START:-N/A} | pod/${API_POD} container state |
SUMMARY

echo
cat "$OUTDIR/summary.txt"
echo
echo "Artifacts written to: $OUTDIR"

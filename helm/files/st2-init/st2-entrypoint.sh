#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

export PYTHONPATH=${PYTHONPATH:-}:/opt/stackstorm/st2/lib/python3.10/site-packages
export PATH=${PATH}:/opt/stackstorm/st2/bin

if [ -f "/app/config/st2_api_key" ] && [ -w /root/.bashrc ]; then
  if ! grep -q "export ST2_API_KEY=" /root/.bashrc 2>/dev/null; then
    echo "export ST2_API_KEY=\$(cat /app/config/st2_api_key)" >> /root/.bashrc
  fi
fi

ST2_CONF_TEMPLATE="/etc/st2/st2.conf.template"
ST2_RUNTIME_DIR="/tmp/st2"
ST2_RUNTIME_CONF="${ST2_RUNTIME_DIR}/st2.conf"

if [ ! -f "${ST2_CONF_TEMPLATE}" ]; then
  log "ERROR: /etc/st2/st2.conf.template not found"
  exit 1
fi

: "${MONGO_USERNAME:?MONGO_USERNAME not set}"
: "${MONGO_PASSWORD:?MONGO_PASSWORD not set}"
: "${RABBITMQ_USER:?RABBITMQ_USER not set}"
: "${RABBITMQ_PASSWORD:?RABBITMQ_PASSWORD not set}"

mkdir -p "${ST2_RUNTIME_DIR}"

if command -v envsubst >/dev/null 2>&1; then
  envsubst '${MONGO_USERNAME} ${MONGO_PASSWORD} ${RABBITMQ_USER} ${RABBITMQ_PASSWORD}' \
    < "${ST2_CONF_TEMPLATE}" > "${ST2_RUNTIME_CONF}"
elif command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
import os
from pathlib import Path

template = Path("/etc/st2/st2.conf.template").read_text()
rendered = template
for key in ("MONGO_USERNAME", "MONGO_PASSWORD", "RABBITMQ_USER", "RABBITMQ_PASSWORD"):
    rendered = rendered.replace("${" + key + "}", os.environ[key])

Path("/tmp/st2/st2.conf").write_text(rendered)
PY
else
  log "ERROR: neither envsubst nor python3 is available for st2.conf templating"
  exit 1
fi

if [ ! -f "${ST2_RUNTIME_CONF}" ]; then
  log "ERROR: Failed to create ${ST2_RUNTIME_CONF}"
  exit 1
fi

rewritten_args=()
for arg in "$@"; do
  if [ "${arg}" = "/etc/st2/st2.conf" ]; then
    rewritten_args+=("${ST2_RUNTIME_CONF}")
  else
    rewritten_args+=("${arg}")
  fi
done

# Some StackStorm image variants move binaries between releases.
# If an absolute command path is missing, retry via PATH by basename.
if [ "${#rewritten_args[@]}" -gt 0 ] && [[ "${rewritten_args[0]}" == /* ]] && [ ! -x "${rewritten_args[0]}" ]; then
  cmd_base="$(basename "${rewritten_args[0]}")"
  resolved_cmd="$(command -v "${cmd_base}" 2>/dev/null || true)"
  if [ -n "${resolved_cmd}" ]; then
    log "Command ${rewritten_args[0]} not found, using ${resolved_cmd}"
    rewritten_args[0]="${resolved_cmd}"
  else
    log "ERROR: command ${rewritten_args[0]} not found and ${cmd_base} is not in PATH"
    exit 1
  fi
fi

exec "${rewritten_args[@]}"

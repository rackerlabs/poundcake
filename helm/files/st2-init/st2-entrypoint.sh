#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

append_shell_export() {
  local key="$1"
  local value="$2"
  local rc_file="${HOME:-}/.bashrc"
  [[ -n "${HOME:-}" ]] || return 0
  [[ -f "${rc_file}" && -w "${rc_file}" ]] || return 0
  grep -Fq -- "export ${key}=" "${rc_file}" 2>/dev/null || echo "export ${key}=${value}" >> "${rc_file}"
}

export PYTHONPATH=${PYTHONPATH:-}:/opt/stackstorm/st2/lib/python3.10/site-packages
export PATH=${PATH}:/opt/stackstorm/st2/bin
export ST2_API_URL="${ST2_API_URL:-http://stackstorm-api:9101}"
export ST2_AUTH_URL="${ST2_AUTH_URL:-http://stackstorm-auth:9100}"
export ST2_SHARED_PACKS_ROOT="${ST2_SHARED_PACKS_ROOT:-/opt/stackstorm/shared-content/packs}"
export ST2_SHARED_VIRTUALENVS_ROOT="${ST2_SHARED_VIRTUALENVS_ROOT:-/opt/stackstorm/shared-content/virtualenvs}"

link_shared_stackstorm_content() {
  local pack_name="$1"
  local shared_pack_path="${ST2_SHARED_PACKS_ROOT}/${pack_name}"
  local shared_virtualenv_path="${ST2_SHARED_VIRTUALENVS_ROOT}/${pack_name}"
  local live_pack_path="/opt/stackstorm/packs/${pack_name}"
  local live_virtualenv_path="/opt/stackstorm/virtualenvs/${pack_name}"

  if [ -d "${ST2_SHARED_PACKS_ROOT}" ]; then
    mkdir -p /opt/stackstorm/packs
    if [ ! -e "${live_pack_path}" ]; then
      ln -s "${shared_pack_path}" "${live_pack_path}"
    fi
  fi

  if [ -d "${ST2_SHARED_VIRTUALENVS_ROOT}" ]; then
    mkdir -p /opt/stackstorm/virtualenvs
    if [ ! -e "${live_virtualenv_path}" ]; then
      ln -s "${shared_virtualenv_path}" "${live_virtualenv_path}"
    fi
  fi
}

if [ -f "/app/config/st2_api_key" ]; then
  append_shell_export "ST2_API_KEY" '$(cat /app/config/st2_api_key)'
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

for shared_pack in kubernetes openstack; do
  link_shared_stackstorm_content "${shared_pack}"
done

if [ "${ST2_CLIENT_AUTO_AUTH:-false}" = "true" ] \
  && [ -z "${ST2_AUTH_TOKEN:-}" ] \
  && [ -n "${ST2_AUTH_USER:-}" ] \
  && [ -n "${ST2_AUTH_PASSWORD:-}" ] \
  && command -v st2 >/dev/null 2>&1; then
  auth_output="$(st2 auth "${ST2_AUTH_USER}" -p "${ST2_AUTH_PASSWORD}" -t 2>&1 || true)"
  auth_token="$(printf '%s\n' "${auth_output}" | tail -n 1 | tr -d '\r')"
  if [ -n "${auth_token}" ] && ! printf '%s' "${auth_token}" | grep -qE '^[[:space:]]*\+'; then
    export ST2_AUTH_TOKEN="${auth_token}"
    append_shell_export "ST2_AUTH_TOKEN" "${auth_token}"
  else
    log "WARN: failed to auto-configure ST2 auth token for interactive client usage"
  fi
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

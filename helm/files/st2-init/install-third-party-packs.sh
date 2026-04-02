#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

STACKSTORM_ROOT="${ST2_PACK_ROOT:-/opt/stackstorm}"

dir_has_content() {
  local dir="$1"
  [[ -d "${dir}" && -n "$(find "${dir}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]
}

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log "ERROR: required command '${cmd}' not found"
    exit 1
  fi
}

default_repo_url() {
  local pack_name="$1"

  case "${pack_name}" in
    kubernetes)
      echo "https://github.com/StackStorm-Exchange/stackstorm-kubernetes.git"
      ;;
    openstack)
      echo "https://github.com/StackStorm-Exchange/stackstorm-openstack.git"
      ;;
    *)
      echo ""
      ;;
  esac
}

install_pack() {
  local pack_name="$1"
  local pack_version="$2"
  local pack_repo_url="$3"
  local pack_ref="${pack_name}"
  local pack_dir="${STACKSTORM_ROOT}/packs/${pack_name}"
  local venv_dir="${STACKSTORM_ROOT}/virtualenvs/${pack_name}"

  if [ -n "${pack_version}" ]; then
    pack_ref="${pack_name}=${pack_version}"
  fi

  if [ -z "${pack_repo_url}" ]; then
    log "ERROR: no repository URL configured for pack ${pack_name}"
    exit 1
  fi

  if dir_has_content "${pack_dir}"; then
    log "Reusing existing StackStorm pack directory ${pack_dir}"
  else
    log "Installing StackStorm pack ${pack_ref} from ${pack_repo_url}"
    rm -rf "${pack_dir}"
    mkdir -p "$(dirname "${pack_dir}")"
    if [ -n "${pack_version}" ]; then
      git clone --depth 1 --branch "${pack_version}" "${pack_repo_url}" "${pack_dir}"
    else
      git clone --depth 1 "${pack_repo_url}" "${pack_dir}"
    fi
  fi

  if dir_has_content "${venv_dir}"; then
    log "Reusing existing StackStorm virtualenv directory ${venv_dir}"
  else
    log "Creating StackStorm virtualenv ${venv_dir}"
    rm -rf "${venv_dir}"
    mkdir -p "$(dirname "${venv_dir}")"
    python3 -m venv --system-site-packages "${venv_dir}"
    "${venv_dir}/bin/pip" install --upgrade pip setuptools wheel
    if [ -f "${pack_dir}/requirements.txt" ]; then
      "${venv_dir}/bin/pip" install -r "${pack_dir}/requirements.txt"
    fi
  fi
}

require_command git
require_command python3

if [ "${ST2_INSTALL_KUBERNETES_PACK:-false}" = "true" ]; then
  install_pack \
    "kubernetes" \
    "${ST2_INSTALL_KUBERNETES_PACK_VERSION:-}" \
    "${ST2_INSTALL_KUBERNETES_PACK_REPO_URL:-$(default_repo_url kubernetes)}"
fi

if [ "${ST2_INSTALL_OPENSTACK_PACK:-false}" = "true" ]; then
  install_pack \
    "openstack" \
    "${ST2_INSTALL_OPENSTACK_PACK_VERSION:-}" \
    "${ST2_INSTALL_OPENSTACK_PACK_REPO_URL:-$(default_repo_url openstack)}"
fi

log "Third-party StackStorm pack installation complete"

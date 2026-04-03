#!/bin/bash
set -euo pipefail

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

STACKSTORM_ROOT="${ST2_PACK_ROOT:-/opt/stackstorm}"

dir_has_meaningful_content() {
  local dir="$1"
  [[ -d "${dir}" && -n "$(find "${dir}" -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit 2>/dev/null)" ]]
}

pack_dir_ready() {
  local dir="$1"
  [[ -f "${dir}/pack.yaml" ]] || dir_has_meaningful_content "${dir}"
}

virtualenv_dir_ready() {
  local dir="$1"
  [[ -x "${dir}/bin/pip" || -f "${dir}/bin/activate" ]]
}

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log "ERROR: required command '${cmd}' not found"
    exit 1
  fi
}

create_virtualenv() {
  local dir="$1"
  local st2_python="${STACKSTORM_ROOT}/st2/bin/python"

  if command -v virtualenv >/dev/null 2>&1; then
    if [ -x "${st2_python}" ]; then
      virtualenv --python "${st2_python}" --system-site-packages "${dir}"
    else
      virtualenv --system-site-packages "${dir}"
    fi
    return 0
  fi

  python3 -m venv --system-site-packages "${dir}"
}

require_value() {
  local label="$1"
  local value="$2"

  if [ -z "${value}" ]; then
    log "ERROR: required value '${label}' is empty"
    exit 1
  fi
}

install_pack_from_exchange() {
  local pack_name="$1"
  local exchange_name="$2"
  local pack_version="$3"
  local pack_ref="${exchange_name}"

  require_command st2
  require_value "exchange pack name for ${pack_name}" "${exchange_name}"

  if [ -n "${pack_version}" ]; then
    pack_ref="${exchange_name}=${pack_version}"
  fi

  log "Installing StackStorm pack ${pack_ref} from StackStorm Exchange"
  st2 pack install "${pack_ref}"
}

install_pack_from_git() {
  local pack_name="$1"
  local pack_version="$2"
  local pack_repo_url="$3"
  local pack_ref="${pack_name}"
  local pack_dir="${STACKSTORM_ROOT}/packs/${pack_name}"
  local venv_dir="${STACKSTORM_ROOT}/virtualenvs/${pack_name}"

  if [ -n "${pack_version}" ]; then
    pack_ref="${pack_name}=${pack_version}"
  fi

  require_command git
  require_command python3
  require_value "git repo url for ${pack_name}" "${pack_repo_url}"

  if pack_dir_ready "${pack_dir}"; then
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

  if virtualenv_dir_ready "${venv_dir}"; then
    log "Reusing existing StackStorm virtualenv directory ${venv_dir}"
  else
    log "Creating StackStorm virtualenv ${venv_dir}"
    rm -rf "${venv_dir}"
    mkdir -p "$(dirname "${venv_dir}")"
    create_virtualenv "${venv_dir}"
    "${venv_dir}/bin/pip" install --upgrade pip setuptools wheel
    if [ -f "${pack_dir}/requirements.txt" ]; then
      "${venv_dir}/bin/pip" install -r "${pack_dir}/requirements.txt"
    fi
  fi
}

install_pack() {
  local pack_name="$1"
  local source_type="$2"
  local source_name="$3"
  local pack_version="$4"
  local pack_repo_url="$5"

  case "${source_type}" in
    exchange)
      install_pack_from_exchange "${pack_name}" "${source_name}" "${pack_version}"
      ;;
    git)
      install_pack_from_git "${pack_name}" "${pack_version}" "${pack_repo_url}"
      ;;
    *)
      log "ERROR: unsupported source type '${source_type}' for pack ${pack_name}"
      exit 1
      ;;
  esac
}

if [ "${ST2_INSTALL_KUBERNETES_PACK:-false}" = "true" ]; then
  install_pack \
    "kubernetes" \
    "${ST2_INSTALL_KUBERNETES_PACK_SOURCE_TYPE:-exchange}" \
    "${ST2_INSTALL_KUBERNETES_PACK_SOURCE_NAME:-kubernetes}" \
    "${ST2_INSTALL_KUBERNETES_PACK_VERSION:-}" \
    "${ST2_INSTALL_KUBERNETES_PACK_REPO_URL:-}"
fi

if [ "${ST2_INSTALL_OPENSTACK_PACK:-false}" = "true" ]; then
  install_pack \
    "openstack" \
    "${ST2_INSTALL_OPENSTACK_PACK_SOURCE_TYPE:-exchange}" \
    "${ST2_INSTALL_OPENSTACK_PACK_SOURCE_NAME:-openstack}" \
    "${ST2_INSTALL_OPENSTACK_PACK_VERSION:-}" \
    "${ST2_INSTALL_OPENSTACK_PACK_REPO_URL:-}"
fi

log "Third-party StackStorm pack installation complete"

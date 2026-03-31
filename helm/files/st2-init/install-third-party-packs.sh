#!/bin/bash
set -euo pipefail

ST2_CONFIG_FILE="${ST2_CONFIG_FILE:-/tmp/st2/st2.conf}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

if [ ! -f "${ST2_CONFIG_FILE}" ]; then
  log "ERROR: StackStorm config file ${ST2_CONFIG_FILE} not found"
  exit 1
fi

install_pack() {
  local pack_name="$1"
  local pack_version="$2"
  local pack_ref="${pack_name}"

  if [ -n "${pack_version}" ]; then
    pack_ref="${pack_name}=${pack_version}"
  fi

  log "Installing StackStorm pack ${pack_ref}"
  st2 pack install "${pack_ref}"
}

if [ "${ST2_INSTALL_KUBERNETES_PACK:-false}" = "true" ]; then
  install_pack "kubernetes" "${ST2_INSTALL_KUBERNETES_PACK_VERSION:-}"
fi

if [ "${ST2_INSTALL_OPENSTACK_PACK:-false}" = "true" ]; then
  install_pack "openstack" "${ST2_INSTALL_OPENSTACK_PACK_VERSION:-}"
fi

log "Registering StackStorm content after third-party pack installation"
st2-register-content \
  --register-all \
  --register-setup-virtualenvs \
  --config-file "${ST2_CONFIG_FILE}"

log "Third-party StackStorm pack installation complete"

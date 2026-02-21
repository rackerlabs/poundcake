#!/bin/bash
set -euo pipefail

PACK_SYNC_URL="${POUNDCAKE_PACK_SYNC_URL:-http://poundcake-api:8000/api/v1/cook/packs}"
PACK_SYNC_TOKEN="${PACK_SYNC_TOKEN:-}"
PACK_SYNC_TIMEOUT="${POUNDCAKE_PACK_SYNC_TIMEOUT:-10}"
POLL_INTERVAL="${POUNDCAKE_PACK_SYNC_POLL_INTERVAL:-20}"
BOOTSTRAP_POLL_INTERVAL="${POUNDCAKE_PACK_SYNC_BOOTSTRAP_INTERVAL:-5}"
PACK_DIR="${POUNDCAKE_PACK_DIR:-/opt/stackstorm/packs/poundcake}"

if [ -z "${PACK_SYNC_TOKEN}" ]; then
  echo "pack-sync: PACK_SYNC_TOKEN is empty"
  exit 1
fi

mkdir -p "${PACK_DIR}"
mkdir -p /tmp/pack-sync

headers_file="/tmp/pack-sync/headers.txt"
archive_file="/tmp/pack-sync/pack.tgz"
last_etag=""

while true; do
  interval="${POLL_INTERVAL}"
  if [ ! -s "${PACK_DIR}/pack.yaml" ]; then
    interval="${BOOTSTRAP_POLL_INTERVAL}"
  fi

  rm -f "${headers_file}" "${archive_file}"

  curl_args=(
    -sS
    --max-time "${PACK_SYNC_TIMEOUT}"
    -D "${headers_file}"
    -o "${archive_file}"
    -H "X-Pack-Sync-Token: ${PACK_SYNC_TOKEN}"
    -w "%{http_code}"
    "${PACK_SYNC_URL}"
  )
  if [ -n "${last_etag}" ]; then
    curl_args+=(-H "If-None-Match: ${last_etag}")
  fi

  http_code="$(curl "${curl_args[@]}" || true)"

  if [ "${http_code}" = "200" ]; then
    tmp_dir="$(mktemp -d /tmp/pack-sync/unpack.XXXXXX)"
    if tar -xzf "${archive_file}" -C "${tmp_dir}"; then
      find "${PACK_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
      cp -a "${tmp_dir}/." "${PACK_DIR}/"
      etag_line="$(grep -i '^etag:' "${headers_file}" | tail -n1 || true)"
      if [ -n "${etag_line}" ]; then
        last_etag="$(echo "${etag_line#*:}" | tr -d '\r' | xargs)"
      fi
      echo "pack-sync: updated pack content"
    else
      echo "pack-sync: failed to extract downloaded archive"
    fi
    rm -rf "${tmp_dir}"
  elif [ "${http_code}" = "304" ]; then
    :
  else
    echo "pack-sync: endpoint returned HTTP ${http_code}"
  fi

  sleep "${interval}"
done

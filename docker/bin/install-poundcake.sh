#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

echo "Installing PoundCake with Docker Compose from: $PROJECT_ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not in PATH"
  exit 1
fi

if ! docker compose -f docker/docker-compose.yml version >/dev/null 2>&1; then
  echo "ERROR: docker compose -f docker/docker-compose.yml is not available"
  exit 1
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

docker compose -f docker/docker-compose.yml up -d "$@"

echo

echo "Current service status:"
docker compose -f docker/docker-compose.yml ps

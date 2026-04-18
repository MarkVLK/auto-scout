#!/bin/bash
set -euo pipefail

ACTION="${1:-up}"
REPO_ROOT="/opt/auto-scout"
COMPOSE_FILE="${REPO_ROOT}/container/docker-compose.yml"

cd "${REPO_ROOT}/container"

if [ "${ACTION}" = "up" ]; then
  exec docker compose -f "${COMPOSE_FILE}" up -d --build companion-runtime
fi

if [ "${ACTION}" = "down" ]; then
  exec docker compose -f "${COMPOSE_FILE}" down
fi

echo "Unsupported action: ${ACTION}" >&2
exit 1

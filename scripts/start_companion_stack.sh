#!/bin/bash
set -euo pipefail

ACTION="${1:-up}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_FILE="${REPO_ROOT}/container/docker-compose.yml"
AUTO_SCOUT_STORAGE_ROOT="${AUTO_SCOUT_STORAGE_ROOT:-/srv/auto-scout}"
export AUTO_SCOUT_STORAGE_ROOT

cd "${REPO_ROOT}/container"

if [ "${ACTION}" = "up" ]; then
  exec docker compose -f "${COMPOSE_FILE}" up -d --build companion-runtime
fi

if [ "${ACTION}" = "down" ]; then
  exec docker compose -f "${COMPOSE_FILE}" down
fi

echo "Unsupported action: ${ACTION}" >&2
exit 1

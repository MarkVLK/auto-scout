#!/bin/bash
set -euo pipefail

ACTION="${1:-up}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_FILE="${REPO_ROOT}/container/docker-compose.yml"
AUTO_SCOUT_STORAGE_ROOT="${AUTO_SCOUT_STORAGE_ROOT:-/srv/auto-scout}"
AUTO_SCOUT_ROS_MASTER_URI="${AUTO_SCOUT_ROS_MASTER_URI:-http://moorebot-scout.local:11311}"
AUTO_SCOUT_ROS_HOSTNAME="${AUTO_SCOUT_ROS_HOSTNAME:-auto-scout-pi5.local}"
export AUTO_SCOUT_STORAGE_ROOT
export AUTO_SCOUT_ROS_MASTER_URI
export AUTO_SCOUT_ROS_HOSTNAME

cd "${REPO_ROOT}/container"

if [ "${ACTION}" = "up" ]; then
  exec docker compose -f "${COMPOSE_FILE}" up -d --build companion-runtime
fi

if [ "${ACTION}" = "down" ]; then
  exec docker compose -f "${COMPOSE_FILE}" down
fi

echo "Unsupported action: ${ACTION}" >&2
exit 1

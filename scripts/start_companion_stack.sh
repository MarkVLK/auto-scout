#!/bin/bash
set -euo pipefail

ACTION="${1:-up}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_FILE="${REPO_ROOT}/container/docker-compose.yml"
DEFAULT_SITE_CONFIG="${REPO_ROOT}/config/site_local.yaml"
if [ ! -f "${DEFAULT_SITE_CONFIG}" ]; then
  DEFAULT_SITE_CONFIG="${REPO_ROOT}/config/site.yaml"
fi
AUTO_SCOUT_SITE_CONFIG="${AUTO_SCOUT_SITE_CONFIG:-${DEFAULT_SITE_CONFIG}}"
AUTO_SCOUT_STORAGE_ROOT="${AUTO_SCOUT_STORAGE_ROOT:-/srv/auto-scout}"
AUTO_SCOUT_LOCALIZATION_MODE="${AUTO_SCOUT_LOCALIZATION_MODE:-false}"
AUTO_SCOUT_ODOM_MODEL_TYPE="${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}"

require_env() {
  local name="$1"
  if [ -n "${!name:-}" ]; then
    return 0
  fi

  echo "${name} must be set before starting companion-runtime." >&2
  echo "For direct docker compose usage, copy container/.env.example to container/.env and fill in your network values." >&2
  exit 1
}

require_env AUTO_SCOUT_ROS_MASTER_URI
require_env AUTO_SCOUT_ROS_HOSTNAME

export AUTO_SCOUT_STORAGE_ROOT
export AUTO_SCOUT_SITE_CONFIG
export AUTO_SCOUT_ROS_MASTER_URI
export AUTO_SCOUT_ROS_HOSTNAME
export AUTO_SCOUT_ODOM_MODEL_TYPE
export AUTO_SCOUT_LOCALIZATION_MODE

cd "${REPO_ROOT}/container"

if [ "${ACTION}" = "up" ]; then
  exec docker compose -f "${COMPOSE_FILE}" up -d --build companion-runtime
fi

if [ "${ACTION}" = "down" ]; then
  exec docker compose -f "${COMPOSE_FILE}" down
fi

echo "Unsupported action: ${ACTION}" >&2
exit 1

#!/bin/bash
set -euo pipefail

ACTION="${1:-up}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMPOSE_FILE="${REPO_ROOT}/container/docker-compose.yml"
CONTAINER_WORKSPACE="/opt/catkin_ws/src/auto-scout"
HOST_SITE_CONFIG="${REPO_ROOT}/config/site_local.yaml"
CONTAINER_SITE_CONFIG="${CONTAINER_WORKSPACE}/config/site_local.yaml"
if [ ! -f "${HOST_SITE_CONFIG}" ]; then
  CONTAINER_SITE_CONFIG="${CONTAINER_WORKSPACE}/config/site.yaml"
fi
AUTO_SCOUT_SITE_CONFIG="${AUTO_SCOUT_SITE_CONFIG:-${CONTAINER_SITE_CONFIG}}"
AUTO_SCOUT_STORAGE_ROOT="${AUTO_SCOUT_STORAGE_ROOT:-/srv/auto-scout}"
AUTO_SCOUT_LOCALIZATION_MODE="${AUTO_SCOUT_LOCALIZATION_MODE:-false}"
AUTO_SCOUT_ENABLE_NAV_STACK="${AUTO_SCOUT_ENABLE_NAV_STACK:-false}"
AUTO_SCOUT_ODOM_MODEL_TYPE="${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}"
AUTO_SCOUT_ROS_LOG_DIR="${AUTO_SCOUT_ROS_LOG_DIR:-${AUTO_SCOUT_STORAGE_ROOT}/ros-logs}"

require_env() {
  local name="$1"
  if [ -n "${!name:-}" ]; then
    return 0
  fi

  echo "${name} must be set before starting companion-runtime." >&2
  echo "For direct docker compose usage, copy container/.env.example to container/.env and fill in your network values." >&2
  exit 1
}

require_ros_advertise_env() {
  if [ -n "${AUTO_SCOUT_ROS_HOSTNAME:-}" ] && [ -n "${AUTO_SCOUT_ROS_IP:-}" ]; then
    echo "Set only one of AUTO_SCOUT_ROS_HOSTNAME or AUTO_SCOUT_ROS_IP before starting companion-runtime." >&2
    exit 1
  fi

  if [ -z "${AUTO_SCOUT_ROS_HOSTNAME:-}" ] && [ -z "${AUTO_SCOUT_ROS_IP:-}" ]; then
    echo "AUTO_SCOUT_ROS_HOSTNAME or AUTO_SCOUT_ROS_IP must be set before starting companion-runtime." >&2
    echo "For direct docker compose usage, copy container/.env.example to container/.env and fill in your network values." >&2
    exit 1
  fi
}

require_env AUTO_SCOUT_ROS_MASTER_URI
require_ros_advertise_env

export AUTO_SCOUT_STORAGE_ROOT
export AUTO_SCOUT_SITE_CONFIG
export AUTO_SCOUT_ROS_MASTER_URI
export AUTO_SCOUT_ROS_HOSTNAME="${AUTO_SCOUT_ROS_HOSTNAME:-}"
export AUTO_SCOUT_ROS_IP="${AUTO_SCOUT_ROS_IP:-}"
export AUTO_SCOUT_ODOM_MODEL_TYPE
export AUTO_SCOUT_LOCALIZATION_MODE
export AUTO_SCOUT_ENABLE_NAV_STACK
export AUTO_SCOUT_ROS_LOG_DIR

cd "${REPO_ROOT}/container"

if [ "${ACTION}" = "up" ]; then
  exec docker compose -f "${COMPOSE_FILE}" up -d --build companion-runtime
fi

if [ "${ACTION}" = "down" ]; then
  exec docker compose -f "${COMPOSE_FILE}" down
fi

echo "Unsupported action: ${ACTION}" >&2
exit 1

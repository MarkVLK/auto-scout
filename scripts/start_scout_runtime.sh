#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CONFIG_FILE="${AUTO_SCOUT_CONFIG:-${REPO_ROOT}/config/scout_config.yaml}"
DEFAULT_SITE_FILE="${REPO_ROOT}/config/site_local.yaml"
if [ ! -f "${DEFAULT_SITE_FILE}" ]; then
  DEFAULT_SITE_FILE="${REPO_ROOT}/config/site.yaml"
fi
SITE_FILE="${AUTO_SCOUT_SITE_CONFIG:-${DEFAULT_SITE_FILE}}"
CAMERA_ENABLED="${AUTO_SCOUT_ENABLE_CAMERA:-false}"
CATKIN_SETUP_DEFAULT="$(cd "${REPO_ROOT}/../.." && pwd)/devel/setup.bash"
CATKIN_SETUP="${AUTO_SCOUT_CATKIN_SETUP:-${CATKIN_SETUP_DEFAULT}}"
WORKSPACE_SRC="$(cd "${REPO_ROOT}/.." && pwd)"

source_runtime_setup() {
  set +u
  source "$1"
  set -u
}

export ROS_DISTRO="${ROS_DISTRO:-melodic}"
export ROS_OS_OVERRIDE="${ROS_OS_OVERRIDE:-debian:stretch}"
source_runtime_setup /opt/ros/melodic/setup.bash
export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"
if [ -f "${CATKIN_SETUP}" ]; then
  source_runtime_setup "${CATKIN_SETUP}"
else
  export ROS_PACKAGE_PATH="${WORKSPACE_SRC}:${ROS_PACKAGE_PATH:-}"
fi

cd "${REPO_ROOT}"
exec roslaunch auto-scout scout_runtime.launch \
  config_file:="${CONFIG_FILE}" \
  site_file:="${SITE_FILE}" \
  enable_camera:="${CAMERA_ENABLED}"

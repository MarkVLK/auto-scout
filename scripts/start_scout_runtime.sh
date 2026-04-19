#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AUTO_SCOUT_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CONFIG_FILE="${AUTO_SCOUT_CONFIG:-${REPO_ROOT}/config/scout_config.yaml}"
SITE_FILE="${AUTO_SCOUT_SITE_CONFIG:-${REPO_ROOT}/config/site.yaml}"
CATKIN_SETUP_DEFAULT="$(cd "${REPO_ROOT}/../.." && pwd)/devel/setup.bash"
CATKIN_SETUP="${AUTO_SCOUT_CATKIN_SETUP:-${CATKIN_SETUP_DEFAULT}}"

source /opt/ros/melodic/setup.bash
if [ -f "${CATKIN_SETUP}" ]; then
  source "${CATKIN_SETUP}"
fi

cd "${REPO_ROOT}"
exec roslaunch auto-scout scout_runtime.launch \
  config_file:="${CONFIG_FILE}" \
  site_file:="${SITE_FILE}"

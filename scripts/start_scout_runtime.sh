#!/bin/bash
set -euo pipefail

source /opt/ros/melodic/setup.bash
if [ -f /home/linaro/catkin_ws/devel/setup.bash ]; then
  source /home/linaro/catkin_ws/devel/setup.bash
fi

cd /home/linaro/catkin_ws/src/auto-scout
exec roslaunch auto-scout scout_runtime.launch \
  config_file:=/home/linaro/catkin_ws/src/auto-scout/config/scout_config.yaml \
  site_file:=/home/linaro/catkin_ws/src/auto-scout/config/site.yaml

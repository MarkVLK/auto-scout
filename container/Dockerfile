FROM ubuntu:18.04

ENV DEBIAN_FRONTEND=noninteractive
# Keep the autonomy stack in a Melodic-era userspace even when the Pi host runs
# Ubuntu 24.04. This avoids turning ros1_bridge or mixed ROS2 distros into the
# default integration boundary before pose and Scout-side interfaces are proven.
ENV ROS_DISTRO=melodic
ENV CATKIN_WS=/opt/catkin_ws

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    gnupg2 \
    lsb-release \
    python \
    python-requests \
    build-essential \
    rsync \
 && rm -rf /var/lib/apt/lists/*

RUN curl -sSL 'https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc' | apt-key add - \
 && echo 'deb http://packages.ros.org/ros/ubuntu bionic main' > /etc/apt/sources.list.d/ros1.list \
 && apt-get update \
 && apt-get install -y \
    python-catkin-tools \
    python-rosdep \
    python-rosinstall \
    python-rosinstall-generator \
    python-vcstools \
    ros-melodic-ros-base \
    ros-melodic-gmapping \
    ros-melodic-amcl \
    ros-melodic-map-server \
    ros-melodic-move-base \
    ros-melodic-dwa-local-planner \
    ros-melodic-global-planner \
    ros-melodic-costmap-2d \
    ros-melodic-explore-lite \
    ros-melodic-joint-state-publisher \
    ros-melodic-robot-state-publisher \
    ros-melodic-rviz \
    ros-melodic-tf2-ros \
    ros-melodic-cv-bridge \
    ros-melodic-image-transport \
 && rm -rf /var/lib/apt/lists/*

RUN rosdep init || true && rosdep update

WORKDIR /opt/catkin_ws/src/auto-scout
COPY . /opt/catkin_ws/src/auto-scout

RUN /bin/bash -lc 'source /opt/ros/melodic/setup.bash && cd /opt/catkin_ws && catkin_make'

ENTRYPOINT ["/opt/catkin_ws/src/auto-scout/container/entrypoint.sh"]

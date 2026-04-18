FROM ubuntu:18.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=melodic
ENV CATKIN_WS=/opt/catkin_ws

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    gnupg2 \
    lsb-release \
    python3 \
    python3-pip \
    python3-rosdep \
    python3-rosinstall \
    python3-rosinstall-generator \
    python3-vcstools \
    build-essential \
    rsync \
 && rm -rf /var/lib/apt/lists/*

RUN curl -sSL 'https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc' | apt-key add - \
 && echo 'deb http://packages.ros.org/ros/ubuntu bionic main' > /etc/apt/sources.list.d/ros1.list \
 && apt-get update \
 && apt-get install -y \
    ros-melodic-ros-base \
    ros-melodic-gmapping \
    ros-melodic-amcl \
    ros-melodic-map-server \
    ros-melodic-move-base \
    ros-melodic-dwa-local-planner \
    ros-melodic-global-planner \
    ros-melodic-costmap-2d \
    ros-melodic-joint-state-publisher \
    ros-melodic-robot-state-publisher \
    ros-melodic-rviz \
    ros-melodic-tf2-ros \
    ros-melodic-cv-bridge \
    ros-melodic-image-transport \
 && rm -rf /var/lib/apt/lists/*

RUN rosdep init || true

WORKDIR /opt/catkin_ws/src/auto-scout
COPY . /opt/catkin_ws/src/auto-scout

RUN /bin/bash -lc 'source /opt/ros/melodic/setup.bash && cd /opt/catkin_ws && catkin_make'

ENTRYPOINT ["/opt/catkin_ws/src/auto-scout/container/entrypoint.sh"]

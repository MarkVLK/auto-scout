cmake_minimum_required(VERSION 3.0.2)
project(auto-scout)

## Find catkin macros and libraries
find_package(catkin REQUIRED COMPONENTS
  rospy
  roscpp
  std_msgs
  geometry_msgs
  sensor_msgs
  nav_msgs
  actionlib_msgs
  tf2
  tf2_ros
  tf2_geometry_msgs
  move_base
  map_server
  amcl
  gmapping
  dwa_local_planner
  global_planner
  costmap_2d
  rviz
  robot_state_publisher
  cv_bridge
  image_transport
)

## System dependencies are found with CMake's conventions
find_package(OpenCV REQUIRED)

## The catkin_package macro generates cmake config files for your package
catkin_package(
  CATKIN_DEPENDS
    rospy
    roscpp
    std_msgs
    geometry_msgs
    sensor_msgs
    nav_msgs
    actionlib_msgs
    tf2
    tf2_ros
    tf2_geometry_msgs
    move_base
    map_server
    amcl
    gmapping
    dwa_local_planner
    global_planner
    costmap_2d
    rviz
    robot_state_publisher
    cv_bridge
    image_transport
)

## Specify additional locations of header files
include_directories(
  ${catkin_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
)

## Mark executable scripts (Python etc.) for installation
catkin_install_python(PROGRAMS
  src/scout_navigation_controller.py
  src/ld19_lidar_driver.py
  src/scout_camera_driver.py
  src/voice_command_interface.py
  src/scout_web_interface.py
  scripts/calibrate_camera.py
  scripts/diagnostics.py
  tests/test_scout_system.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

## Mark other files for installation
install(DIRECTORY
  launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  config/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/config
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  urdf/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/urdf
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  rviz/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/rviz
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  templates/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/templates
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  systemd/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/systemd
  PATTERN ".svn" EXCLUDE
)

## Mark files for installation
install(FILES
  README.md
  setup_guide.md
  install.sh
  package.xml
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

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
  actionlib
  tf2
  tf2_ros
  tf2_geometry_msgs
  move_base_msgs
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
    actionlib
    tf2
    tf2_ros
    tf2_geometry_msgs
    move_base_msgs
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
)

## Mark executable scripts (Python etc.) for installation
catkin_install_python(PROGRAMS
  check_scout_compatibility.py
  src/scout_navigation_controller.py
  src/scout_runtime_agent.py
  src/companion_runtime_agent.py
  src/map_file_guard.py
  src/ld19_lidar_driver.py
  src/scout_camera_driver.py
  src/scout_tof_bridge.py
  src/scout_imu_bridge.py
  src/scout_safety_filter.py
  src/scout_battery_dock_guard.py
  src/battery_map_return_controller.py
  src/scout_motion_bridge.py
  src/scout_odom_bridge.py
  src/vendor_jpg_bridge.py
  src/dog_detection_module.py
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
  docs/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/docs
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  systemd/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/systemd
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  container/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/container
  PATTERN ".svn" EXCLUDE
)

install(DIRECTORY
  scripts/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/scripts
  PATTERN ".svn" EXCLUDE
)

install(FILES
  auto-scout
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

## Mark files for installation
install(FILES
  README.md
  docs/setup_guide.md
  package.xml
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

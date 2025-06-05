# Changelog

All notable changes to the Auto-Scout project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-06-04

### Added
- **Dog Search Functionality**: Complete room-by-room dog finding system
  - Voice commands: "Find dog" and "Stop dog search"
  - Computer vision-based dog detection using camera
  - Automatic photo capture when dog is found
  - Room identification and location reporting
  - Systematic search through predefined room order
  - Automatic return to charging dock after search completion
- **Enhanced Navigation Controller**: 
  - Dog search state machine integration
  - Thread-safe operation with existing navigation
  - Configurable search parameters and room order
- **Detection Module**: 
  - Room-specific detection activation
  - Support for both PyTorch and OpenCV detection models
  - Photo upload capabilities
- **Project Structure**: Reorganized following ROS and Python best practices
- **Documentation**: Comprehensive dog search integration documentation

### Changed
- Updated README.md with dog search features and usage instructions
- Enhanced voice command processing to include dog search commands
- Improved status publishing to include dog search progress
- Restructured project directories for better organization

### Technical Details
- Integration between `scout_navigation_controller.py` and `dog_detection_module.py`
- Added `detection_active` state variable for proper detection control
- Enhanced configuration system with dog search parameters
- Thread-safe state management for concurrent navigation and detection

## [1.0.0] - 2025-05-XX

### Added
- **Core Navigation System**: Autonomous navigation using FHL-LD19 Lidar
- **SLAM Mapping**: Real-time mapping and localization
- **Voice Commands**: Speech recognition and control interface
- **Web Dashboard**: Real-time robot status and control interface
- **Scheduled Patrols**: Automated patrol routing with time-based scheduling
- **Safety Features**: Emergency stop, obstacle avoidance, battery monitoring
- **ROS Integration**: Complete ROS-based architecture
- **Camera Integration**: Visual odometry and image capture
- **Multi-room Navigation**: Waypoint-based house navigation

### Core Components
- `scout_navigation_controller.py` - Main navigation logic
- `ld19_lidar_driver.py` - Lidar sensor interface
- `scout_camera_driver.py` - Camera driver and processing
- `scout_web_interface.py` - Web-based control dashboard
- `voice_command_interface.py` - Voice control system

### Configuration
- Navigation parameter files for ROS move_base
- Robot URDF description
- Launch files for different operational modes
- Systemd service files for auto-startup

### Documentation
- Installation guide and setup instructions
- Quick start guide for new users
- Comprehensive README with feature overview

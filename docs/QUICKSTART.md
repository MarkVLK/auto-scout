# Moorebot Scout Quick Start Guide

This guide will help you get your Moorebot Scout autonomous navigation system up and running quickly.

## Prerequisites

- Moorebot Scout robot with Linux capability
- youyeetoo FHL-LD19 Lidar sensor connected via USB
- USB camera (built-in or external)
- Microphone and speakers for voice commands
- WiFi connection

## Quick Installation

### 1. Automated Installation (Recommended)

```bash
# Clone the repository
git clone <repository-url> auto-scout
cd auto-scout

# Run the automated installation script
sudo ./install.sh
```

The installation script will:
- Install ROS Melodic
- Install all Python dependencies
- Set up system services
- Configure audio permissions
- Create necessary directories

### 2. Manual Installation

If the automated script fails, follow the detailed [Setup Guide](setup_guide.md).

## First-Time Setup

### 1. Camera Calibration

For optimal visual odometry performance, calibrate your camera:

```bash
# Run camera calibration
./scripts/calibrate_camera.py
```

Follow the on-screen instructions to capture calibration images using a chessboard pattern.

### 2. System Check

Run diagnostics to verify all components:

```bash
# Check system health
./scripts/diagnostics.py
```

This will verify hardware connections, software dependencies, and system configuration.

## Basic Operation

### 1. Start the Complete System

```bash
# Start all components
roslaunch auto-scout scout_complete.launch
```

### 2. Access Web Dashboard

Open your browser and navigate to:
```
http://localhost:5000
```

The web dashboard provides:
- Live camera feed
- Lidar visualization  
- Robot status monitoring
- Manual controls
- Schedule management

### 3. Voice Commands

The system responds to these voice commands:
- "Start patrol" - Begin autonomous patrolling
- "Stop" - Stop current operation
- "Go to [location]" - Navigate to specific area
- "Return home" - Return to charging station
- "Emergency stop" - Immediate stop

### 4. Create a Map

#### Using SLAM (Simultaneous Localization and Mapping):

```bash
# Start SLAM mapping
roslaunch auto-scout slam_mapping.launch
```

Drive the robot around manually or use voice commands to explore the area. The map will be built in real-time.

#### Save the Map:

```bash
# Save the current map
rosrun map_server map_saver -f my_house_map
```

### 5. Autonomous Navigation

Once you have a map, switch to navigation mode:

```bash
# Load saved map and start navigation
roslaunch auto-scout navigation.launch map_file:=my_house_map.yaml
```

## Scheduled Operation

### Set Up Patrol Schedule

1. Open the web dashboard
2. Go to "Schedule" tab
3. Add patrol times and locations
4. Enable automatic scheduling

Example schedule:
- 9 AM: Patrol living room and kitchen
- 2 PM: Check bedroom and office
- 6 PM: General house patrol

### Monitor Operation

The web dashboard shows:
- Current robot state
- Battery level
- Last known position
- Error messages
- System logs

## Safety Features

The system includes several safety mechanisms:

- **Obstacle Avoidance**: Automatic stopping and rerouting around obstacles
- **Cliff Detection**: Prevents falls from stairs or elevated surfaces
- **Emergency Stop**: Voice command or manual button for immediate stop
- **Low Battery Return**: Automatic return to charging station
- **Stuck Detection**: Automatic recovery from stuck situations
- **Collision Prevention**: Multiple sensor fusion for safe navigation

## Troubleshooting

### Common Issues

1. **No Lidar Data**
   - Check USB connection
   - Verify `/dev/ttyUSB0` exists
   - Run diagnostics script

2. **Camera Not Working**
   - Check camera connection
   - Try different camera index
   - Run camera calibration

3. **Voice Commands Not Recognized**
   - Check microphone permissions
   - Verify audio devices in diagnostics
   - Test microphone levels

4. **Navigation Problems**
   - Recalibrate camera
   - Check map quality
   - Verify transform frames

### Getting Help

1. **Run Diagnostics**:
   ```bash
   ./scripts/diagnostics.py
   ```

2. **Check Logs**:
   ```bash
   # ROS logs
   roscd auto-scout
   cat ~/.ros/log/latest/rosout.log
   
   # System service logs
   sudo journalctl -u scout-navigation -f
   ```

3. **Test Individual Components**:
   ```bash
   # Test Lidar
   rosrun auto-scout ld19_lidar_driver.py
   
   # Test camera
   rosrun auto-scout scout_camera_driver.py
   
   # Test voice
   rosrun auto-scout voice_command_interface.py
   ```

## Advanced Configuration

### Customize Navigation Parameters

Edit configuration files in `config/` directory:
- `scout_config.yaml` - Main robot parameters
- `costmap_common_params.yaml` - Obstacle avoidance settings
- `base_local_planner_params.yaml` - Movement planning

### Add New Voice Commands

Edit `src/voice_command_interface.py` to add custom commands and responses.

### Modify Web Interface

Edit `templates/dashboard.html` and `src/scout_web_interface.py` to customize the web dashboard.

## Performance Tips

1. **Optimize for Your Environment**:
   - Adjust Lidar range based on room size
   - Tune movement speeds for your floors
   - Calibrate camera for your lighting

2. **Battery Life**:
   - Set conservative movement speeds
   - Use scheduled operation during optimal times
   - Monitor battery levels regularly

3. **Mapping Quality**:
   - Move slowly during initial mapping
   - Ensure good lighting for visual odometry
   - Map during typical operating conditions

## System Services

The system runs as background services:

```bash
# Check service status
sudo systemctl status scout-navigation
sudo systemctl status scout-web

# Restart services
sudo systemctl restart scout-navigation
sudo systemctl restart scout-web

# View service logs
sudo journalctl -u scout-navigation -f
```

## Emergency Procedures

### Emergency Stop
- Voice: "Emergency stop"
- Web dashboard: Red emergency button
- Physical: Unplug power

### System Recovery
```bash
# Stop all services
sudo systemctl stop scout-navigation scout-web

# Restart ROS
sudo pkill -f ros
roscore &

# Restart services
sudo systemctl start scout-navigation scout-web
```

### Factory Reset
```bash
# Reset configuration
rm -rf ~/.ros/log/*
rm config/camera_calibration.*
rm maps/*

# Restart system
sudo reboot
```

## Support

For additional support:
1. Check the [full documentation](../README.md)
2. Review the [detailed setup guide](setup_guide.md)
3. Run the diagnostic script for specific errors
4. Check GitHub issues for known problems

---

**Happy Scouting! 🤖**

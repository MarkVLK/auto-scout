# Auto-Scout: Autonomous Navigation System

[![Project Status](https://img.shields.io/badge/Status-Ready%20for%20Development-brightgreen)](https://github.com/your-repo/auto-scout)
[![Python](https://img.shields.io/badge/Python-3.7%2B-blue)](https://python.org)
[![ROS](https://img.shields.io/badge/ROS-Noetic-blue)](https://wiki.ros.org/noetic)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Transform your Moorebot Scout into a fully autonomous robot capable of mapping your house and navigating according to schedules or voice commands using the youyeetoo FHL-LD19 Lidar sensor.

## Features

- 🗺️ **SLAM Mapping**: Create detailed maps of your house using Lidar and camera data
- 🤖 **Autonomous Navigation**: Navigate through pre-defined waypoints with obstacle avoidance
- 📅 **Scheduled Patrols**: Set up automatic patrol routes on a schedule
- 🗣️ **Voice Commands**: Control the robot with voice commands
- 🐕 **Dog Finding**: Search the house room-by-room to find your dog, take photos, and report location
- 📱 **ROS Integration**: Full ROS-based architecture for extensibility
- 🔋 **Safety Features**: Emergency stop, low battery handling, obstacle detection
- 📊 **Visual Odometry**: Enhanced localization using camera and IMU fusion

## Hardware Requirements

- Moorebot Scout robot
- youyeetoo FHL-LD19 Lidar sensor
- USB-to-TTL converter for Lidar connection
- MicroSD card (32GB+ recommended)
- Optional: External battery pack for extended operation

## Quick Start

1. **Hardware Setup**: Connect the FHL-LD19 Lidar to your Scout via USB
2. **Software Installation**: Run the automated installation script
3. **Initial Mapping**: Create a map of your environment
4. **Configure Waypoints**: Set up navigation points for your house
5. **Schedule Patrols**: Configure autonomous patrol schedules

## Installation

### Automated Installation (Recommended)

SSH into your Moorebot Scout and run:

```bash
# Download and run the installation script
wget https://raw.githubusercontent.com/your-repo/auto-scout/main/install.sh
chmod +x install.sh
./install.sh
```

### Manual Installation

See [setup_guide.md](docs/setup_guide.md) for detailed manual installation instructions.

## Usage

### Starting the System

```bash
cd /home/linaro/scout_navigation
./start_navigation.sh
```

### Voice Commands

- "Start patrol" - Begin autonomous patrol
- "Stop patrol" - End patrol and stop
- "Go home" - Return to home position
- "Go kitchen" - Navigate to kitchen
- "Go living room" - Navigate to living room
- "Go bedroom" - Navigate to bedroom
- "Find dog" - Search the house room-by-room for your dog
- "Stop dog search" - Cancel active dog search
- "Emergency stop" - Immediate stop
- "Save map" - Save current SLAM map

### ROS Commands

```bash
# Manual movement
rostopic pub /cmd_vel geometry_msgs/Twist "linear: {x: 0.2}" 

# Navigate to waypoint
rostopic pub /scout/command std_msgs/String "go_kitchen"

# Start dog search
rostopic pub /scout/command std_msgs/String "find_dog"

# Stop dog search
rostopic pub /scout/command std_msgs/String "stop_dog_search"

# Emergency stop
rostopic pub /scout/emergency_stop std_msgs/Bool true

# Check robot status
rostopic echo /scout/status
```

### Dog Search Feature

The robot can autonomously search your house to find your dog:

1. **Voice Command**: Say "Find dog" to start the search
2. **Systematic Search**: The robot will visit each room in a predefined order
3. **Computer Vision**: Uses the camera to detect and identify dogs
4. **Photo Capture**: Takes a photo when a dog is found
5. **Location Reporting**: Reports which room the dog was found in
6. **Return Home**: Automatically returns to the charging dock when complete

The search covers these rooms in order:
- Living room
- Kitchen  
- Bedroom
- Office
- Bathroom
- Hallway

Search parameters can be configured in the robot's settings:
- Maximum search time: 10 minutes
- Time per room: 30 seconds
- Photo upload destination
- Room search order

## Configuration

The robot can be configured by editing the configuration file:

```bash
# Main configuration file
config/scout_config.yaml

# Example configuration with all options
examples/configs/scout_config_example.yaml
```

### Key Configuration Sections

- **Navigation**: Speed limits, goal tolerance, obstacle avoidance
- **Dog Search**: Search timing, room order, detection confidence
- **House Layout**: Room coordinates and waypoints  
- **Voice Commands**: Custom command mappings
- **Safety**: Emergency stops, battery thresholds
- **Logging**: Log levels and file locations

See `examples/configs/scout_config_example.yaml` for detailed configuration options.

## Project Structure

```
auto-scout/
├── src/                    # Python source modules
├── launch/                 # ROS launch files
├── config/                 # Configuration files
├── tests/                  # Test suite
├── docs/                   # Documentation
├── examples/               # Example configs and demos
├── tools/                  # Development and deployment tools
├── scripts/                # Utility scripts
├── systemd/                # System service files
├── templates/              # Web interface templates
├── urdf/                   # Robot description files
└── rviz/                   # Visualization configurations
```

## Development

### Setting Up Development Environment

```bash
# Run the development setup script
./tools/setup_dev.sh

# Or manually set up
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_dog_search_integration.py

# Run with coverage
python -m pytest --cov=src tests/
```

### Development Commands

```bash
scout-build    # Build ROS workspace
scout-test     # Run test suite  
scout-lint     # Check code style
scout-run      # Launch complete system
scout-logs     # View system logs
```

## Deployment

Deploy to your robot using the deployment script:

```bash
# Deploy to robot (replace IP and username)
./tools/deploy.sh 192.168.1.100 ubuntu

# Script will:
# - Copy files to robot
# - Install dependencies  
# - Build ROS workspace
# - Start services
```

## System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Moorebot Scout │    │   FHL-LD19       │    │  Host Computer  │
│  - Camera       │<-->│   Lidar Sensor   │<-->│  - ROS Master   │
│  - IMU          │    │   - 360° scan    │    │  - SLAM         │
│  - Motors       │    │   - 12m range    │    │  - Path Plan    │
│  - WiFi         │    │   - 8000Hz       │    │  - Scheduling   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Safety Features

- **Emergency Stop**: Multiple ways to immediately stop the robot
- **Obstacle Avoidance**: Real-time obstacle detection and avoidance
- **Battery Monitoring**: Automatic return to charging station when low
- **Network Monitoring**: Handles WiFi disconnections gracefully
- **Mechanical Limits**: Accounts for Scout's wheel slippage and inaccuracies

## Troubleshooting

### Common Issues

1. **Lidar not detected**
   ```bash
   ls -la /dev/ttyUSB*
   sudo chmod 666 /dev/ttyUSB0
   ```

2. **Poor navigation accuracy**
   - Calibrate wheel odometry
   - Adjust SLAM parameters
   - Ensure good lighting for visual odometry

3. **Voice commands not working**
   - Check microphone permissions
   - Verify internet connection for speech recognition
   - Test with manual commands first

### Debug Commands

```bash
# Check ROS topics
rostopic list

# Monitor Lidar data
rostopic echo /scan

# View camera feed
rosrun image_view image_view image:=/camera/image_raw

# Check transforms
rosrun tf tf_monitor
```

## Development

### Project Structure

```
auto-scout/
├── config/          # Configuration files
├── launch/          # ROS launch files
├── src/             # Python source code
├── urdf/            # Robot description files
├── install.sh       # Installation script
├── docs/            # Documentation
└── tests/           # Test files
```

### Adding New Features

1. Create new ROS nodes in `src/`
2. Add launch configurations in `launch/`
3. Update configuration in `config/scout_config.yaml`
4. Test thoroughly before deployment

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test on actual hardware
4. Submit a pull request

## License

This project is open source. See LICENSE file for details.

## Acknowledgments

- [Moorebot](https://www.moorebot.com/) for creating an accessible Linux-based robot
- [youyeetoo](https://www.youyeetoo.com/) for the FHL-LD19 Lidar sensor
- [ROS Community](https://www.ros.org/) for the robotics framework
- Nicole Faerber's [blog post](https://www.dpin.de/nf/moorebot-scout-as-linux-as-it-can-get/) for Scout insights

## Support

- Create an issue for bugs or feature requests
- Check the [setup guide](docs/setup_guide.md) for detailed instructions
- Join the community discussions

---

**Note**: This system enhances the Scout's capabilities but cannot completely overcome its mechanical limitations (wheel slippage, gear backlash). For best results, use in well-lit environments with good visual landmarks.

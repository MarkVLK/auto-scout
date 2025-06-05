# Moorebot Scout Autonomous Navigation Setup Guide

This guide will help you set up the Moorebot Scout with the youyeetoo FHL-LD19 Lidar sensor for autonomous navigation and SLAM mapping.

## Hardware Requirements

- Moorebot Scout robot
- youyeetoo FHL-LD19 Lidar sensor
- USB to TTL converter (for Lidar communication)
- MicroSD card (32GB+ recommended for data logging)
- External battery pack (optional, for extended operation)

## System Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Moorebot Scout │    │   FHL-LD19       │    │  Host Computer  │
│  - Camera       │<-->│   Lidar Sensor   │<-->│  - ROS Master   │
│  - IMU          │    │   - 360° scan    │    │  - SLAM         │
│  - Motors       │    │   - 12m range    │    │  - Path Plan    │
│  - WiFi         │    │   - 8000Hz       │    │  - Scheduling   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Phase 1: Scout Setup and Access

### 1.1 Initial Scout Configuration

1. Power on the Scout and connect to its WiFi network
2. Complete initial setup using the Moorebot app
3. Find the Scout's IP address (usually starts with 192.168.1.x)
4. SSH into the Scout:

```bash
ssh linaro@<scout-ip-address>
# Default password: linaro
```

### 1.2 Enable Root Access

Once logged in, edit the RC file to enable sudo:

```bash
sudo nano /etc/rc.local
```

Add this line before `exit 0`:
```bash
chmod 4755 /usr/bin/sudo
```

Reboot the Scout:
```bash
sudo reboot
```

After reboot, you can get root access:
```bash
sudo su -
```

## Phase 2: System Updates and Dependencies

### 2.1 Update the System

```bash
# Update package lists
sudo apt update

# Install essential packages
sudo apt install -y \
    python3-pip \
    python3-dev \
    build-essential \
    git \
    cmake \
    pkg-config \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libgtk-3-dev \
    libatlas-base-dev \
    gfortran \
    python3-numpy
```

### 2.2 Install ROS Dependencies

```bash
# Install additional ROS packages
sudo apt install -y \
    ros-kinetic-navigation \
    ros-kinetic-slam-gmapping \
    ros-kinetic-move-base \
    ros-kinetic-amcl \
    ros-kinetic-map-server \
    ros-kinetic-robot-localization
```

## Phase 3: Lidar Integration

### 3.1 Hardware Connection

1. Connect the FHL-LD19 Lidar to the Scout via USB-to-TTL converter
2. The Lidar typically uses:
   - Red wire: VCC (5V)
   - Black wire: GND
   - White wire: TX
   - Green wire: RX

### 3.2 Lidar Driver Installation

Create the Lidar driver package:

```bash
cd /home/linaro
mkdir -p catkin_ws/src
cd catkin_ws/src
git clone https://github.com/ldrobotSensorTeam/ldlidar_ros.git
cd ..
catkin_make
source devel/setup.bash
```

## Phase 4: SLAM Configuration

### 4.1 Create SLAM Launch File

Create a launch file for SLAM mapping:

```bash
mkdir -p /home/linaro/catkin_ws/src/scout_navigation/launch
```

### 4.2 Navigation Stack Setup

The navigation stack will combine:
- Lidar data for obstacle detection and mapping
- Camera data for visual landmarks
- IMU data for orientation
- Odometry from wheel encoders (with corrections)

## Phase 5: Computer Vision Integration

### 5.1 Camera Calibration

The Scout's camera needs calibration for accurate visual odometry and landmark detection.

### 5.2 Visual-Inertial Odometry

Combine camera and IMU data to improve localization accuracy, compensating for the Scout's mechanical imprecision.

## Phase 6: Scheduling and Autonomous Operation

### 6.1 Mission Planning

Create a mission planner that can:
- Execute scheduled patrols
- Respond to voice commands
- Handle emergency stops
- Return to charging station

### 6.2 Safety Systems

Implement multiple layers of safety:
- Emergency stop via WiFi command
- Obstacle avoidance using all sensors
- Battery monitoring and auto-return
- Network connectivity monitoring

## Next Steps

1. Hardware integration and testing
2. Sensor calibration
3. SLAM tuning for your environment
4. Path planning optimization
5. Scheduling system implementation
6. Safety system validation

## Troubleshooting

### Common Issues

1. **Lidar not detected**: Check USB permissions and baud rate
2. **Poor SLAM performance**: Adjust scan matching parameters
3. **Navigation errors**: Calibrate wheel odometry and IMU
4. **WiFi connectivity**: Set up static IP and network redundancy

### Debug Commands

```bash
# Check ROS topics
rostopic list

# Monitor Lidar data
rostopic echo /scan

# Check transform tree
rosrun tf tf_monitor

# View camera feed
rosrun image_view image_view image:=/camera/image_raw
```

## Resources

- [ROS Navigation Tuning Guide](http://wiki.ros.org/navigation/Tutorials/Navigation%20Tuning%20Guide)
- [SLAM Tuning Parameters](http://wiki.ros.org/gmapping)
- [Visual-Inertial Odometry](https://github.com/HKUST-Aerial-Robotics/VINS-Mono)

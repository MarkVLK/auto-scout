#!/bin/bash

# Moorebot Scout Autonomous Navigation Installation Script
# This script sets up the complete system for autonomous navigation

set -e

echo "=========================================="
echo "Moorebot Scout Autonomous Navigation Setup"
echo "=========================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Scout
check_environment() {
    log_info "Checking environment..."
    
    if [ "$(whoami)" != "linaro" ]; then
        log_warn "Not running as 'linaro' user. This script is designed for Moorebot Scout."
    fi
    
    if [ ! -f /etc/debian_version ]; then
        log_error "This script requires Debian-based system"
        exit 1
    fi
    
    log_info "Environment check completed"
}

# Update system packages
update_system() {
    log_info "Updating system packages..."
    
    sudo apt update
    sudo apt upgrade -y
    
    log_info "System update completed"
}

# Install dependencies
install_dependencies() {
    log_info "Installing dependencies..."
    
    # Python dependencies
    sudo apt install -y \
        python3-pip \
        python3-dev \
        python3-numpy \
        python3-opencv \
        python3-serial \
        python3-yaml \
        python3-scipy \
        python3-matplotlib
    
    # Development tools
    sudo apt install -y \
        build-essential \
        cmake \
        git \
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
        gfortran
    
    # ROS dependencies (if not already installed)
    sudo apt install -y \
        ros-kinetic-navigation \
        ros-kinetic-slam-gmapping \
        ros-kinetic-move-base \
        ros-kinetic-amcl \
        ros-kinetic-map-server \
        ros-kinetic-robot-localization \
        ros-kinetic-tf2-tools \
        ros-kinetic-robot-state-publisher \
        ros-kinetic-joint-state-publisher
    
    # Python packages via pip
    pip3 install --user \
        pyserial \
        opencv-python \
        speechrecognition \
        pyttsx3 \
        pyaudio
    
    log_info "Dependencies installation completed"
}

# Setup ROS workspace
setup_ros_workspace() {
    log_info "Setting up ROS workspace..."
    
    # Create catkin workspace
    mkdir -p /home/linaro/catkin_ws/src
    cd /home/linaro/catkin_ws
    
    # Source ROS
    source /opt/ros/kinetic/setup.bash
    
    # Initialize workspace
    catkin_make
    
    # Add to bashrc if not already present
    if ! grep -q "source /home/linaro/catkin_ws/devel/setup.bash" ~/.bashrc; then
        echo "source /home/linaro/catkin_ws/devel/setup.bash" >> ~/.bashrc
    fi
    
    log_info "ROS workspace setup completed"
}

# Install Lidar driver
install_lidar_driver() {
    log_info "Installing Lidar driver..."
    
    cd /home/linaro/catkin_ws/src
    
    # Clone Lidar driver repository
    if [ ! -d "ldlidar_ros" ]; then
        git clone https://github.com/ldrobotSensorTeam/ldlidar_ros.git
    fi
    
    # Build workspace
    cd /home/linaro/catkin_ws
    source /opt/ros/kinetic/setup.bash
    catkin_make
    
    log_info "Lidar driver installation completed"
}

# Copy project files
copy_project_files() {
    log_info "Copying project files..."
    
    # Create directories
    mkdir -p /home/linaro/scout_navigation/{launch,config,src,urdf,maps,scripts}
    
    # Copy files (assuming they're in current directory)
    if [ -f "launch/slam_mapping.launch" ]; then
        cp launch/*.launch /home/linaro/scout_navigation/launch/
    fi
    
    if [ -f "config/scout_config.yaml" ]; then
        cp config/*.yaml /home/linaro/scout_navigation/config/
    fi
    
    if [ -f "src/scout_navigation_controller.py" ]; then
        cp src/*.py /home/linaro/scout_navigation/src/
        chmod +x /home/linaro/scout_navigation/src/*.py
    fi
    
    if [ -f "urdf/scout.urdf" ]; then
        cp urdf/*.urdf /home/linaro/scout_navigation/urdf/
    fi
    
    # Copy this script
    cp "$0" /home/linaro/scout_navigation/scripts/
    
    log_info "Project files copied"
}

# Setup udev rules for devices
setup_udev_rules() {
    log_info "Setting up udev rules..."
    
    # Lidar USB device rule
    sudo tee /etc/udev/rules.d/99-lidar.rules > /dev/null <<EOF
# youyeetoo FHL-LD19 Lidar
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="lidar", MODE="0666"

# Generic USB-to-Serial converters
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="ftdi_device", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", SYMLINK+="pl2303_device", MODE="0666"
EOF
    
    # Camera device rule
    sudo tee /etc/udev/rules.d/99-camera.rules > /dev/null <<EOF
# Scout camera
SUBSYSTEM=="video4linux", KERNEL=="video*", ATTRS{name}=="*usb*", MODE="0666", GROUP="video"
EOF
    
    # Reload udev rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    
    log_info "Udev rules setup completed"
}

# Create systemd services
create_systemd_services() {
    log_info "Creating systemd services..."
    
    # Scout navigation service
    sudo tee /etc/systemd/system/scout-navigation.service > /dev/null <<EOF
[Unit]
Description=Scout Autonomous Navigation
After=network.target
Wants=network.target

[Service]
Type=simple
User=linaro
Group=linaro
WorkingDirectory=/home/linaro/scout_navigation
Environment=ROS_MASTER_URI=http://localhost:11311
Environment=ROS_HOSTNAME=localhost
ExecStartPre=/bin/bash -c 'source /opt/ros/kinetic/setup.bash && source /home/linaro/catkin_ws/devel/setup.bash'
ExecStart=/bin/bash -c 'source /opt/ros/kinetic/setup.bash && source /home/linaro/catkin_ws/devel/setup.bash && python3 /home/linaro/scout_navigation/src/scout_navigation_controller.py'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # Voice command service
    sudo tee /etc/systemd/system/scout-voice.service > /dev/null <<EOF
[Unit]
Description=Scout Voice Command Interface
After=network.target scout-navigation.service
Wants=network.target

[Service]
Type=simple
User=linaro
Group=linaro
WorkingDirectory=/home/linaro/scout_navigation
Environment=ROS_MASTER_URI=http://localhost:11311
Environment=ROS_HOSTNAME=localhost
ExecStartPre=/bin/bash -c 'source /opt/ros/kinetic/setup.bash && source /home/linaro/catkin_ws/devel/setup.bash'
ExecStart=/bin/bash -c 'source /opt/ros/kinetic/setup.bash && source /home/linaro/catkin_ws/devel/setup.bash && python3 /home/linaro/scout_navigation/src/voice_command_interface.py'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Don't enable services yet - user should test first
    log_info "Systemd services created (not enabled)"
    log_info "To enable: sudo systemctl enable scout-navigation scout-voice"
}

# Create helper scripts
create_helper_scripts() {
    log_info "Creating helper scripts..."
    
    # Start script
    tee /home/linaro/scout_navigation/start_navigation.sh > /dev/null <<'EOF'
#!/bin/bash
# Start Scout Navigation System

source /opt/ros/kinetic/setup.bash
source /home/linaro/catkin_ws/devel/setup.bash

echo "Starting Scout Navigation System..."

# Start roscore in background
roscore &
ROSCORE_PID=$!
sleep 2

# Start SLAM mapping
roslaunch scout_navigation slam_mapping.launch &
SLAM_PID=$!
sleep 3

# Start navigation controller
python3 /home/linaro/scout_navigation/src/scout_navigation_controller.py &
NAV_PID=$!

# Start voice interface (optional)
# python3 /home/linaro/scout_navigation/src/voice_command_interface.py &
# VOICE_PID=$!

echo "Navigation system started"
echo "Press Ctrl+C to stop"

# Wait for interrupt
trap 'kill $ROSCORE_PID $SLAM_PID $NAV_PID 2>/dev/null' EXIT
wait
EOF
    
    # Stop script
    tee /home/linaro/scout_navigation/stop_navigation.sh > /dev/null <<'EOF'
#!/bin/bash
# Stop Scout Navigation System

echo "Stopping Scout Navigation System..."

# Kill all related processes
pkill -f scout_navigation_controller.py
pkill -f voice_command_interface.py
pkill -f slam_gmapping
pkill -f move_base
pkill -f roscore

echo "Navigation system stopped"
EOF
    
    # Test script
    tee /home/linaro/scout_navigation/test_sensors.sh > /dev/null <<'EOF'
#!/bin/bash
# Test Scout Sensors

source /opt/ros/kinetic/setup.bash
source /home/linaro/catkin_ws/devel/setup.bash

echo "Testing Scout sensors..."

# Test Lidar
echo "Testing Lidar connection..."
if [ -e /dev/ttyUSB0 ]; then
    echo "✓ Lidar device found at /dev/ttyUSB0"
else
    echo "✗ Lidar device not found"
fi

# Test camera
echo "Testing camera..."
if [ -e /dev/video0 ]; then
    echo "✓ Camera device found at /dev/video0"
else
    echo "✗ Camera device not found"
fi

# Test ROS
echo "Testing ROS setup..."
if command -v roscore >/dev/null 2>&1; then
    echo "✓ ROS installation found"
else
    echo "✗ ROS not found"
fi

echo "Sensor test completed"
EOF
    
    chmod +x /home/linaro/scout_navigation/*.sh
    
    log_info "Helper scripts created"
}

# Final setup
final_setup() {
    log_info "Performing final setup..."
    
    # Set permissions
    sudo chown -R linaro:linaro /home/linaro/scout_navigation
    sudo chown -R linaro:linaro /home/linaro/catkin_ws
    
    # Add user to required groups
    sudo usermod -a -G dialout,video,audio linaro
    
    log_info "Final setup completed"
}

# Print instructions
print_instructions() {
    echo ""
    echo "=========================================="
    echo "          INSTALLATION COMPLETE"
    echo "=========================================="
    echo ""
    log_info "Next steps:"
    echo ""
    echo "1. Reboot the system to apply all changes:"
    echo "   sudo reboot"
    echo ""
    echo "2. Connect your FHL-LD19 Lidar to USB port"
    echo ""
    echo "3. Test the sensors:"
    echo "   cd /home/linaro/scout_navigation"
    echo "   ./test_sensors.sh"
    echo ""
    echo "4. Start the navigation system:"
    echo "   ./start_navigation.sh"
    echo ""
    echo "5. To create a map, drive the robot around manually first:"
    echo "   rostopic pub /cmd_vel geometry_msgs/Twist ..."
    echo ""
    echo "6. Save the map when satisfied:"
    echo "   rostopic pub /scout/command std_msgs/String 'save_map'"
    echo ""
    echo "7. Enable automatic startup (optional):"
    echo "   sudo systemctl enable scout-navigation"
    echo "   sudo systemctl enable scout-voice"
    echo ""
    echo "Configuration files:"
    echo "- /home/linaro/scout_navigation/config/scout_config.yaml"
    echo "- /home/linaro/scout_navigation/launch/*.launch"
    echo ""
    echo "Log files will be in:"
    echo "- ~/.ros/log/"
    echo ""
    log_info "Happy autonomous navigation!"
}

# Main installation process
main() {
    check_environment
    update_system
    install_dependencies
    setup_ros_workspace
    install_lidar_driver
    copy_project_files
    setup_udev_rules
    create_systemd_services
    create_helper_scripts
    final_setup
    print_instructions
}

# Run main installation
main "$@"

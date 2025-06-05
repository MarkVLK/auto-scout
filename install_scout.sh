#!/bin/bash
# Scout Installation Script for auto-scout project
# Optimized for Debian Stretch + ROS Melodic + ARM64

set -e  # Exit on any error

echo "🤖 Auto-Scout Installation for Moorebot Scout"
echo "=============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root"
    exit 1
fi

# Check system compatibility
print_status "Checking system compatibility..."

# Check architecture
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    print_warning "Expected ARM64 architecture, found: $ARCH"
fi

# Check Debian version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$VERSION_ID" != "9" ]; then
        print_warning "Expected Debian 9 (Stretch), found: $PRETTY_NAME"
    else
        print_status "Running on Debian Stretch - compatible"
    fi
fi

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
print_status "Python version: $PYTHON_VERSION"

# Update package lists
print_status "Updating package lists..."
sudo apt update

# Install system dependencies
print_status "Installing system dependencies..."
sudo apt install -y \
    python3-pip \
    python3-dev \
    python3-setuptools \
    build-essential \
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
    libasound2-dev \
    portaudio19-dev

# Install ROS Melodic packages
print_status "Installing ROS Melodic packages..."
sudo apt install -y \
    ros-melodic-navigation \
    ros-melodic-gmapping \
    ros-melodic-amcl \
    ros-melodic-map-server \
    ros-melodic-tf2-tools \
    ros-melodic-robot-localization \
    ros-melodic-teleop-twist-keyboard \
    ros-melodic-rviz \
    ros-melodic-robot-state-publisher \
    ros-melodic-joint-state-publisher

# Check if ROS environment is set up
if ! grep -q "source /opt/ros/melodic/setup.bash" ~/.bashrc; then
    print_status "Setting up ROS environment..."
    echo "source /opt/ros/melodic/setup.bash" >> ~/.bashrc
    source /opt/ros/melodic/setup.bash
fi

# Upgrade pip
print_status "Upgrading pip..."
python3 -m pip install --user --upgrade pip

# Install Python dependencies with ARM64/Debian Stretch compatible versions
print_status "Installing Python dependencies..."

# Install numpy first (required for many other packages)
python3 -m pip install --user "numpy>=1.16.0,<1.20.0"

# Install other dependencies
python3 -m pip install --user -r requirements.txt

# Install the auto-scout package in development mode
print_status "Installing auto-scout package..."
python3 -m pip install --user -e .

# Add user to dialout group for serial access
if ! groups $USER | grep -q dialout; then
    print_status "Adding user to dialout group for serial access..."
    sudo usermod -a -G dialout $USER
    print_warning "You need to log out and log back in for group changes to take effect"
fi

# Create systemd services directory if it doesn't exist
if [ ! -d ~/.config/systemd/user ]; then
    mkdir -p ~/.config/systemd/user
fi

# Set up systemd user services
print_status "Setting up systemd services..."
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload

# Enable services (but don't start them yet)
systemctl --user enable scout-navigation.service
systemctl --user enable scout-web.service

print_status "Creating log directory..."
mkdir -p ~/logs

# Run compatibility check
print_status "Running compatibility check..."
if python3 check_scout_compatibility.py; then
    print_status "✅ Installation completed successfully!"
else
    print_warning "⚠️  Installation completed with warnings"
fi

echo ""
echo "🎉 Auto-Scout Installation Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Log out and log back in (for dialout group)"
echo "2. Test installation: python3 -c 'import src; print(\"Import successful!\")'"
echo "3. Start services: systemctl --user start scout-navigation scout-web"
echo "4. Check logs: journalctl --user -u scout-navigation -f"
echo ""
echo "Web interface will be available at: http://scout-ip:5000"
echo ""
echo "For development:"
echo "  pip3 install --user -e .[dev]"
echo ""

print_status "Installation script completed!"

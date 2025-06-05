#!/bin/bash
# Development Environment Setup Script for Auto-Scout

set -e

echo "🤖 Auto-Scout Development Environment Setup"
echo "============================================"

# Check if we're in the right directory
if [ ! -f "package.xml" ]; then
    echo "❌ Error: Run this script from the auto-scout project root directory"
    exit 1
fi

# Check for ROS installation
echo "📋 Checking ROS installation..."
if [ -z "$ROS_DISTRO" ]; then
    echo "⚠️  ROS environment not detected. Please source ROS setup:"
    echo "   source /opt/ros/noetic/setup.bash"
    exit 1
fi
echo "✓ ROS $ROS_DISTRO detected"

# Check Python version
echo "📋 Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
if [ "$(echo "$PYTHON_VERSION >= 3.8" | bc -l 2>/dev/null || echo 0)" != "1" ]; then
    echo "❌ Python 3.8+ required, found $PYTHON_VERSION"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION detected"

# Create virtual environment for development
echo "🐍 Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment and install dependencies
echo "📦 Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Install pre-commit hooks (if available)
if command -v pre-commit &> /dev/null; then
    echo "🔧 Setting up pre-commit hooks..."
    pip install pre-commit
    pre-commit install
    echo "✓ Pre-commit hooks installed"
fi

# Set up ROS workspace
echo "🏗️  Setting up ROS workspace..."
if [ ! -d "$HOME/catkin_ws/src" ]; then
    mkdir -p $HOME/catkin_ws/src
    cd $HOME/catkin_ws
    catkin_make
    echo "✓ Created catkin workspace"
    cd - > /dev/null
fi

# Link project to catkin workspace
PROJECT_DIR=$(pwd)
CATKIN_LINK="$HOME/catkin_ws/src/auto-scout"
if [ ! -L "$CATKIN_LINK" ]; then
    ln -s "$PROJECT_DIR" "$CATKIN_LINK"
    echo "✓ Linked project to catkin workspace"
else
    echo "✓ Project already linked to catkin workspace"
fi

# Install ROS dependencies
echo "📦 Installing ROS dependencies..."
cd $HOME/catkin_ws
rosdep update
rosdep install --from-paths src --ignore-src -r -y
echo "✓ ROS dependencies installed"

# Build the workspace
echo "🔨 Building ROS workspace..."
catkin_make
echo "✓ Workspace built successfully"

# Source the workspace
echo "📋 Setting up environment..."
if ! grep -q "source $HOME/catkin_ws/devel/setup.bash" ~/.bashrc; then
    echo "source $HOME/catkin_ws/devel/setup.bash" >> ~/.bashrc
    echo "✓ Added workspace to ~/.bashrc"
fi

# Create development aliases
echo "⚡ Setting up development aliases..."
DEV_ALIASES="
# Auto-Scout development aliases
alias scout-build='cd $HOME/catkin_ws && catkin_make'
alias scout-test='cd $HOME/catkin_ws/src/auto-scout && python -m pytest tests/'
alias scout-lint='cd $HOME/catkin_ws/src/auto-scout && python -m flake8 src/'
alias scout-run='roslaunch auto-scout scout_complete.launch'
alias scout-nav='roslaunch auto-scout navigation.launch'
alias scout-slam='roslaunch auto-scout slam_mapping.launch'
alias scout-logs='tail -f ~/.ros/log/latest/rosout.log'
"

if ! grep -q "# Auto-Scout development aliases" ~/.bashrc; then
    echo "$DEV_ALIASES" >> ~/.bashrc
    echo "✓ Added development aliases to ~/.bashrc"
fi

# Create development configuration
echo "⚙️  Creating development configuration..."
if [ ! -f "config/scout_config_dev.yaml" ]; then
    cp "examples/configs/scout_config_example.yaml" "config/scout_config_dev.yaml"
    echo "✓ Created development config file"
fi

# Set up log directory
echo "📝 Setting up logging..."
sudo mkdir -p /var/log/scout
sudo chown $USER:$USER /var/log/scout
echo "✓ Log directory created"

# Create systemd services for development
echo "🔧 Setting up development services..."
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
echo "✓ Systemd services installed"

echo ""
echo "✅ Development environment setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Restart your terminal or run: source ~/.bashrc"
echo "2. Test the build: scout-build"
echo "3. Run tests: scout-test"
echo "4. Start development: scout-run"
echo ""
echo "🔧 Development commands:"
echo "  scout-build  - Build the ROS workspace"
echo "  scout-test   - Run test suite"
echo "  scout-lint   - Check code style"
echo "  scout-run    - Launch complete system"
echo "  scout-nav    - Launch navigation only"
echo "  scout-slam   - Launch SLAM mapping"
echo "  scout-logs   - View system logs"
echo ""
echo "📁 Important files:"
echo "  config/scout_config_dev.yaml - Development configuration"
echo "  /var/log/scout/ - Log files"
echo "  ~/.ros/log/latest/ - ROS logs"
echo ""
echo "Happy developing! 🚀"

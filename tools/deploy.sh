#!/bin/bash
# Deployment Script for Auto-Scout Robot

set -e

ROBOT_IP=${1:-"192.168.1.100"}
ROBOT_USER=${2:-"ubuntu"}
TARGET_DIR="/home/$ROBOT_USER/catkin_ws/src/auto-scout"

echo "🚀 Auto-Scout Deployment Script"
echo "================================"
echo "Target: $ROBOT_USER@$ROBOT_IP:$TARGET_DIR"
echo ""

# Check if we can reach the robot
echo "📡 Checking robot connectivity..."
if ! ping -c 1 "$ROBOT_IP" &> /dev/null; then
    echo "❌ Cannot reach robot at $ROBOT_IP"
    echo "Please check network connection and robot IP address"
    exit 1
fi
echo "✓ Robot reachable"

# Check SSH access
echo "🔑 Checking SSH access..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$ROBOT_USER@$ROBOT_IP" exit &> /dev/null; then
    echo "❌ Cannot SSH to robot"
    echo "Please set up SSH key authentication:"
    echo "  ssh-copy-id $ROBOT_USER@$ROBOT_IP"
    exit 1
fi
echo "✓ SSH access confirmed"

# Create backup of current deployment
echo "💾 Creating backup on robot..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    if [ -d '$TARGET_DIR' ]; then
        sudo cp -r '$TARGET_DIR' '${TARGET_DIR}.backup.$(date +%Y%m%d_%H%M%S)'
        echo '✓ Backup created'
    else
        echo '✓ No existing deployment to backup'
    fi
"

# Stop running services
echo "⏹️  Stopping robot services..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    sudo systemctl stop scout-navigation.service || true
    sudo systemctl stop scout-web.service || true
    echo '✓ Services stopped'
"

# Create target directory
echo "📁 Preparing target directory..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    mkdir -p '$TARGET_DIR'
    echo '✓ Target directory ready'
"

# Copy source files
echo "📤 Copying source files..."
rsync -avz --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='venv' \
    --exclude='.pytest_cache' \
    --exclude='docs/' \
    --exclude='examples/' \
    --exclude='tools/' \
    --exclude='tests/' \
    ./ "$ROBOT_USER@$ROBOT_IP:$TARGET_DIR/"
echo "✓ Source files copied"

# Copy configuration if it doesn't exist
echo "⚙️  Setting up configuration..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    if [ ! -f '$TARGET_DIR/config/scout_config.yaml' ]; then
        cp '$TARGET_DIR/examples/configs/scout_config_example.yaml' '$TARGET_DIR/config/scout_config.yaml'
        echo '✓ Default configuration installed'
    else
        echo '✓ Existing configuration preserved'
    fi
"

# Install/update dependencies
echo "📦 Installing dependencies..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    cd '$TARGET_DIR'
    
    # Install Python dependencies
    pip3 install -r requirements.txt
    
    # Install ROS dependencies
    cd ~/catkin_ws
    rosdep update
    rosdep install --from-paths src --ignore-src -r -y
    
    echo '✓ Dependencies installed'
"

# Build the workspace
echo "🔨 Building ROS workspace..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    cd ~/catkin_ws
    catkin_make
    echo '✓ Workspace built'
"

# Update systemd services
echo "🔧 Updating system services..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    sudo cp '$TARGET_DIR/systemd/'*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable scout-navigation.service
    sudo systemctl enable scout-web.service
    echo '✓ Services updated'
"

# Set up log directory
echo "📝 Setting up logging..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    sudo mkdir -p /var/log/scout
    sudo chown $ROBOT_USER:$ROBOT_USER /var/log/scout
    echo '✓ Logging configured'
"

# Start services
echo "▶️  Starting robot services..."
ssh "$ROBOT_USER@$ROBOT_IP" "
    source ~/catkin_ws/devel/setup.bash
    sudo systemctl start scout-navigation.service
    sudo systemctl start scout-web.service
    echo '✓ Services started'
"

# Verify deployment
echo "🔍 Verifying deployment..."
sleep 5

ssh "$ROBOT_USER@$ROBOT_IP" "
    # Check service status
    if systemctl is-active --quiet scout-navigation.service; then
        echo '✓ Navigation service running'
    else
        echo '❌ Navigation service failed'
        systemctl status scout-navigation.service --no-pager -l
    fi
    
    if systemctl is-active --quiet scout-web.service; then
        echo '✓ Web service running'
    else
        echo '❌ Web service failed'
        systemctl status scout-web.service --no-pager -l
    fi
"

# Test web interface
echo "🌐 Testing web interface..."
if curl -s "http://$ROBOT_IP:8080" > /dev/null; then
    echo "✓ Web interface accessible at http://$ROBOT_IP:8080"
else
    echo "⚠️  Web interface not yet available (may still be starting)"
fi

echo ""
echo "✅ Deployment completed successfully!"
echo ""
echo "📋 Post-deployment checklist:"
echo "1. Test web interface: http://$ROBOT_IP:8080"
echo "2. Test voice commands: 'Find dog'"
echo "3. Check logs: ssh $ROBOT_USER@$ROBOT_IP 'tail -f /var/log/scout/scout.log'"
echo "4. Test navigation: Use web interface or voice commands"
echo ""
echo "🔧 Useful commands:"
echo "  # View service status"
echo "  ssh $ROBOT_USER@$ROBOT_IP 'systemctl status scout-navigation.service'"
echo ""
echo "  # View logs"
echo "  ssh $ROBOT_USER@$ROBOT_IP 'journalctl -u scout-navigation.service -f'"
echo ""
echo "  # Restart services"
echo "  ssh $ROBOT_USER@$ROBOT_IP 'sudo systemctl restart scout-navigation.service'"
echo ""
echo "🎉 Robot is ready for dog finding missions!"

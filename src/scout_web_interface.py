#!/usr/bin/env python3
"""
Web interface for Scout robot monitoring and control
Provides a web dashboard for status monitoring and manual control
"""

import rospy
import json
import yaml
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit
import cv2
import numpy as np
from std_msgs.msg import String, Bool
from sensor_msgs.msg import LaserScan, CompressedImage
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid
import base64
from threading import Thread, Lock
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'scout_robot_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

class ScoutWebInterface:
    """
    Web interface for Scout robot control and monitoring
    """
    
    def __init__(self):
        # Initialize ROS node
        rospy.init_node('scout_web_interface', anonymous=True)
        
        # State variables
        self.robot_status = {}
        self.latest_image = None
        self.latest_scan = None
        self.latest_map = None
        self.connected_clients = 0
        
        # Locks for thread safety
        self.status_lock = Lock()
        self.image_lock = Lock()
        self.scan_lock = Lock()
        
        # Load configuration
        try:
            with open('/home/linaro/scout_navigation/config/scout_config.yaml', 'r') as f:
                self.config = yaml.safe_load(f)
        except:
            self.config = {'waypoints': {}, 'schedules': []}
        
        # ROS Publishers
        self.cmd_vel_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.command_pub = rospy.Publisher('/scout/command', String, queue_size=1)
        self.emergency_pub = rospy.Publisher('/scout/emergency_stop', Bool, queue_size=1)
        
        # ROS Subscribers
        self.status_sub = rospy.Subscriber('/scout/status', String, self.status_callback)
        self.image_sub = rospy.Subscriber('/camera/image_raw/compressed', 
                                        CompressedImage, self.image_callback)
        self.scan_sub = rospy.Subscriber('/scan', LaserScan, self.scan_callback)
        self.map_sub = rospy.Subscriber('/map', OccupancyGrid, self.map_callback)
        
        rospy.loginfo("Scout web interface initialized")
    
    def status_callback(self, msg):
        """Handle robot status updates"""
        try:
            with self.status_lock:
                self.robot_status = json.loads(msg.data)
                self.robot_status['last_update'] = time.time()
            
            # Emit to connected clients
            socketio.emit('status_update', self.robot_status)
            
        except Exception as e:
            rospy.logwarn("Error processing status: {}".format(e))
    
    def image_callback(self, msg):
        """Handle camera image updates"""
        try:
            with self.image_lock:
                # Convert compressed image to base64 for web transmission
                self.latest_image = base64.b64encode(msg.data).decode('utf-8')
            
            # Emit to connected clients (throttled)
            if self.connected_clients > 0:
                socketio.emit('image_update', {'image': self.latest_image})
                
        except Exception as e:
            rospy.logwarn("Error processing image: {}".format(e))
    
    def scan_callback(self, msg):
        """Handle lidar scan updates"""
        try:
            # Convert scan to JSON format
            scan_data = {
                'angle_min': msg.angle_min,
                'angle_max': msg.angle_max,
                'angle_increment': msg.angle_increment,
                'range_min': msg.range_min,
                'range_max': msg.range_max,
                'ranges': [r if r != float('inf') else msg.range_max for r in msg.ranges]
            }
            
            with self.scan_lock:
                self.latest_scan = scan_data
            
            # Emit to connected clients (throttled)
            if self.connected_clients > 0:
                socketio.emit('scan_update', scan_data)
                
        except Exception as e:
            rospy.logwarn("Error processing scan: {}".format(e))
    
    def map_callback(self, msg):
        """Handle map updates"""
        try:
            # Convert occupancy grid to image
            map_array = np.array(msg.data).reshape((msg.info.height, msg.info.width))
            
            # Convert to 8-bit image (0=free, 128=unknown, 255=occupied)
            map_image = np.zeros_like(map_array, dtype=np.uint8)
            map_image[map_array == 0] = 255    # Free space = white
            map_image[map_array == 100] = 0    # Occupied = black
            map_image[map_array == -1] = 128   # Unknown = gray
            
            # Convert to base64
            _, encoded = cv2.imencode('.png', map_image)
            map_b64 = base64.b64encode(encoded).decode('utf-8')
            
            self.latest_map = {
                'image': map_b64,
                'resolution': msg.info.resolution,
                'width': msg.info.width,
                'height': msg.info.height,
                'origin_x': msg.info.origin.position.x,
                'origin_y': msg.info.origin.position.y
            }
            
            # Emit to connected clients
            socketio.emit('map_update', self.latest_map)
            
        except Exception as e:
            rospy.logwarn("Error processing map: {}".format(e))

# Global interface instance
interface = None

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    """Get current robot status"""
    with interface.status_lock:
        return jsonify(interface.robot_status)

@app.route('/api/config')
def get_config():
    """Get robot configuration"""
    return jsonify(interface.config)

@app.route('/api/command', methods=['POST'])
def send_command():
    """Send command to robot"""
    try:
        data = request.get_json()
        command = data.get('command', '')
        
        if command:
            interface.command_pub.publish(command)
            return jsonify({'success': True, 'message': 'Command sent: {}'.format(command)})
        else:
            return jsonify({'success': False, 'message': 'No command provided'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/move', methods=['POST'])
def move_robot():
    """Send movement command to robot"""
    try:
        data = request.get_json()
        
        twist = Twist()
        twist.linear.x = data.get('linear_x', 0.0)
        twist.linear.y = data.get('linear_y', 0.0)
        twist.angular.z = data.get('angular_z', 0.0)
        
        interface.cmd_vel_pub.publish(twist)
        
        return jsonify({'success': True, 'message': 'Movement command sent'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/emergency_stop', methods=['POST'])
def emergency_stop():
    """Trigger emergency stop"""
    try:
        data = request.get_json()
        stop = data.get('stop', True)
        
        interface.emergency_pub.publish(Bool(stop))
        
        return jsonify({'success': True, 'message': 'Emergency stop triggered'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    global interface
    interface.connected_clients += 1
    rospy.loginfo("Client connected. Total clients: {}".format(interface.connected_clients))
    
    # Send initial data
    emit('status_update', interface.robot_status)
    if interface.latest_image:
        emit('image_update', {'image': interface.latest_image})
    if interface.latest_scan:
        emit('scan_update', interface.latest_scan)
    if interface.latest_map:
        emit('map_update', interface.latest_map)

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    global interface
    interface.connected_clients = max(0, interface.connected_clients - 1)
    rospy.loginfo("Client disconnected. Total clients: {}".format(interface.connected_clients))

@socketio.on('command')
def handle_command(data):
    """Handle command from web client"""
    command = data.get('command', '')
    if command:
        interface.command_pub.publish(command)
        emit('command_response', {'success': True, 'command': command})

def run_flask_app():
    """Run Flask app in separate thread"""
    socketio.run(app, host='0.0.0.0', port=8080, debug=False)

def main():
    """Main function"""
    global interface
    
    try:
        # Initialize interface
        interface = ScoutWebInterface()
        
        # Start Flask app in separate thread
        flask_thread = Thread(target=run_flask_app)
        flask_thread.daemon = True
        flask_thread.start()
        
        rospy.loginfo("Scout web interface running on http://0.0.0.0:8080")
        
        # Keep ROS spinning
        rospy.spin()
        
    except rospy.ROSInterruptException:
        rospy.loginfo("Scout web interface shutting down")
    except Exception as e:
        rospy.logerr("Error in scout web interface: {}".format(e))

if __name__ == '__main__':
    main()

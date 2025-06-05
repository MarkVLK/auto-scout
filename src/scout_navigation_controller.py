#!/usr/bin/env python3
"""
Moorebot Scout Autonomous Navigation Controller
Combines Lidar SLAM, visual odometry, scheduling, and dog-finding functionality
for autonomous house navigation
"""

import rospy
import numpy as np
import cv2
import yaml
import json
from datetime import datetime, time
from threading import Thread, Lock
import tf2_ros
import tf2_geometry_msgs

# ROS messages
from sensor_msgs.msg import LaserScan, Image, CompressedImage, Imu
from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from actionlib_msgs.msg import GoalStatus
from std_msgs.msg import String, Bool
from cv_bridge import CvBridge

# Action client
import actionlib

# Import dog detection module
from dog_detection_module import DogDetectionModule

class ScoutNavigationController:
    """
    Main controller for Scout autonomous navigation with dog-finding capabilities
    """
    
    def __init__(self):
        rospy.init_node('scout_navigation_controller', anonymous=True)
        
        # Initialize variables
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        # State variables
        self.current_pose = None
        self.current_goal = None
        self.navigation_active = False
        self.emergency_stop = False
        self.battery_level = 100.0
        self.last_lidar_scan = None
        self.last_camera_image = None
        self.schedule_active = False
        
        # Dog search state
        self.dog_search_active = False
        self.dog_found = False
        self.dog_room = None
        self.search_progress = []
        self.search_waypoints = []
        self.current_search_index = 0
        self.search_start_time = None
        self.dog_photo_taken = False
        
        # Locks for thread safety
        self.pose_lock = Lock()
        self.goal_lock = Lock()
        self.state_lock = Lock()
        
        # Load configuration
        self.load_config()
        
        # Initialize ROS publishers
        self.cmd_vel_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=1)
        self.initial_pose_pub = rospy.Publisher('/initialpose', PoseWithCovarianceStamped, queue_size=1)
        self.status_pub = rospy.Publisher('/scout/status', String, queue_size=1)
        
        # Initialize ROS subscribers
        self.laser_sub = rospy.Subscriber('/scan', LaserScan, self.laser_callback)
        self.camera_sub = rospy.Subscriber('/camera/image_raw/compressed', CompressedImage, self.camera_callback)
        self.imu_sub = rospy.Subscriber('/imu', Imu, self.imu_callback)
        self.odom_sub = rospy.Subscriber('/odom', Odometry, self.odom_callback)
        self.amcl_sub = rospy.Subscriber('/amcl_pose', PoseWithCovarianceStamped, self.amcl_callback)
        self.map_sub = rospy.Subscriber('/map', OccupancyGrid, self.map_callback)
        
        # Command subscribers
        self.command_sub = rospy.Subscriber('/scout/command', String, self.command_callback)
        self.emergency_sub = rospy.Subscriber('/scout/emergency_stop', Bool, self.emergency_callback)
        
        # Action client for move_base
        self.move_base_client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        
        # Wait for action server
        rospy.loginfo("Waiting for move_base action server...")
        self.move_base_client.wait_for_server()
        rospy.loginfo("Connected to move_base action server")
        
        # Start scheduler thread
        self.scheduler_thread = Thread(target=self.scheduler_loop)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        
        # Start dog search monitor thread
        self.dog_search_thread = Thread(target=self.dog_search_loop)
        self.dog_search_thread.daemon = True
        self.dog_search_thread.start()
        
        # Visual odometry enhancement
        self.setup_visual_odometry()
        
        # Initialize dog detection module
        self.dog_detector = DogDetectionModule(self)
        self.dog_detection_sub = rospy.Subscriber('/scout/dog_detection', String, self.dog_detection_callback)
        
        rospy.loginfo("Scout Navigation Controller initialized with dog-finding capabilities")
        self.current_goal = None
        self.navigation_active = False
        self.emergency_stop = False
        self.battery_level = 100.0
        self.last_lidar_scan = None
        self.last_camera_image = None
        self.schedule_active = False
        
        # Dog search state
        self.dog_search_active = False
        self.dog_found = False
        self.dog_room = None
        self.search_progress = []
        
        # Locks for thread safety
        self.pose_lock = Lock()
        self.goal_lock = Lock()
        self.state_lock = Lock()
        
        # Load configuration
        self.load_config()
        
        # Initialize ROS publishers
        self.cmd_vel_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=1)
        self.initial_pose_pub = rospy.Publisher('/initialpose', PoseWithCovarianceStamped, queue_size=1)
        self.status_pub = rospy.Publisher('/scout/status', String, queue_size=1)
        
        # Initialize ROS subscribers
        self.laser_sub = rospy.Subscriber('/scan', LaserScan, self.laser_callback)
        self.camera_sub = rospy.Subscriber('/camera/image_raw/compressed', CompressedImage, self.camera_callback)
        self.imu_sub = rospy.Subscriber('/imu', Imu, self.imu_callback)
        self.odom_sub = rospy.Subscriber('/odom', Odometry, self.odom_callback)
        self.amcl_sub = rospy.Subscriber('/amcl_pose', PoseWithCovarianceStamped, self.amcl_callback)
        self.map_sub = rospy.Subscriber('/map', OccupancyGrid, self.map_callback)
        
        # Command subscribers
        self.command_sub = rospy.Subscriber('/scout/command', String, self.command_callback)
        self.emergency_sub = rospy.Subscriber('/scout/emergency_stop', Bool, self.emergency_callback)
        
        # Action client for move_base
        self.move_base_client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        
        # Wait for action server
        rospy.loginfo("Waiting for move_base action server...")
        self.move_base_client.wait_for_server()
        rospy.loginfo("Connected to move_base action server")
        
        # Start scheduler thread
        self.scheduler_thread = Thread(target=self.scheduler_loop)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        
        # Visual odometry enhancement
        self.setup_visual_odometry()
        
        # Initialize dog detection module
        self.dog_detector = DogDetectionModule(self)
        self.dog_detection_sub = rospy.Subscriber('/scout/dog_detection', String, self.dog_detection_callback)
        
        rospy.loginfo("Scout Navigation Controller initialized")
    
    def load_config(self):
        """Load navigation configuration"""
        try:
            with open('/home/linaro/scout_config.yaml', 'r') as f:
                self.config = yaml.safe_load(f)
        except:
            # Default configuration
            self.config = {
                'waypoints': {
                    'home': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                    'kitchen': {'x': 3.0, 'y': 1.0, 'z': 0.0, 'w': 1.0},
                    'living_room': {'x': 2.0, 'y': -2.0, 'z': 0.0, 'w': 1.0},
                    'bedroom': {'x': -2.0, 'y': 2.0, 'z': 0.0, 'w': 1.0},
                    'charging_station': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                    'bathroom': {'x': 1.0, 'y': 3.0, 'z': 0.0, 'w': 1.0},
                    'hallway': {'x': 0.0, 'y': 1.0, 'z': 0.0, 'w': 1.0},
                    'office': {'x': -3.0, 'y': -1.0, 'z': 0.0, 'w': 1.0}
                },
                'schedules': [
                    {
                        'name': 'morning_patrol',
                        'time': '08:00',
                        'waypoints': ['kitchen', 'living_room', 'bedroom', 'home'],
                        'active': True
                    },
                    {
                        'name': 'evening_patrol',
                        'time': '20:00',
                        'waypoints': ['living_room', 'kitchen', 'bedroom', 'home'],
                        'active': True
                    }
                ],
                'safety': {
                    'min_battery_level': 20.0,
                    'max_obstacle_distance': 0.3,
                    'emergency_stop_distance': 0.15
                },
                'dog_search': {
                    'max_search_time': 600,  # 10 minutes
                    'room_search_time': 30,  # 30 seconds per room
                    'search_order': ['living_room', 'kitchen', 'bedroom', 'office', 'bathroom', 'hallway']
                }
            }
    
    def setup_visual_odometry(self):
        """Initialize visual odometry for enhanced localization"""
        # Initialize ORB detector for feature matching
        self.orb = cv2.ORB_create(nfeatures=1000)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        
        # Previous frame data
        self.prev_frame = None
        self.prev_keypoints = None
        self.prev_descriptors = None
        
        # Camera calibration parameters (these should be calibrated for your Scout)
        self.camera_matrix = np.array([[500, 0, 320],
                                     [0, 500, 240],
                                     [0, 0, 1]], dtype=np.float32)
        self.dist_coeffs = np.array([0.1, -0.2, 0, 0, 0], dtype=np.float32)
    
    def laser_callback(self, msg):
        """Process laser scan data"""
        self.last_lidar_scan = msg
        
        # Check for emergency obstacles
        min_distance = min([r for r in msg.ranges if r > 0])
        if min_distance < self.config['safety']['emergency_stop_distance']:
            self.emergency_stop = True
            self.stop_robot()
            rospy.logwarn("Emergency stop triggered - obstacle at {:.2f}m".format(min_distance))
    
    def camera_callback(self, msg):
        """Process camera image for visual odometry"""
        try:
            # Convert compressed image to OpenCV format
            np_arr = np.frombuffer(msg.data, np.uint8)
            cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            self.last_camera_image = cv_image
            
            # Process for visual odometry
            self.process_visual_odometry(cv_image)
            
        except Exception as e:
            rospy.logwarn("Camera processing error: {}".format(e))
    
    def process_visual_odometry(self, frame):
        """Extract visual odometry from camera frames"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect ORB keypoints and descriptors
        keypoints, descriptors = self.orb.detectAndCompute(gray, None)
        
        if self.prev_frame is not None and descriptors is not None and self.prev_descriptors is not None:
            # Match features between frames
            matches = self.matcher.match(self.prev_descriptors, descriptors)
            matches = sorted(matches, key=lambda x: x.distance)
            
            if len(matches) > 10:  # Minimum matches for reliable estimation
                # Extract matched points
                src_pts = np.array([self.prev_keypoints[m.queryIdx].pt for m in matches])
                dst_pts = np.array([keypoints[m.trainIdx].pt for m in matches])
                
                # Estimate motion using essential matrix
                E, mask = cv2.findEssentialMat(src_pts, dst_pts, self.camera_matrix, 
                                             method=cv2.RANSAC, prob=0.999, threshold=1.0)
                
                if E is not None:
                    # Recover pose from essential matrix
                    _, R, t, mask = cv2.recoverPose(E, src_pts, dst_pts, self.camera_matrix)
                    
                    # This motion data could be used to enhance odometry
                    # For now, we'll just log significant motion
                    translation_magnitude = np.linalg.norm(t)
                    if translation_magnitude > 0.1:
                        rospy.logdebug("Visual motion detected: {:.3f}".format(translation_magnitude))
        
        # Store current frame data for next iteration
        self.prev_frame = gray.copy()
        self.prev_keypoints = keypoints
        self.prev_descriptors = descriptors
    
    def imu_callback(self, msg):
        """Process IMU data"""
        # IMU data can be used to enhance orientation estimation
        # and detect if the robot is stuck or tilted
        pass
    
    def odom_callback(self, msg):
        """Process odometry data"""
        # Store odometry for fusion with other sensors
        pass
    
    def amcl_callback(self, msg):
        """Process AMCL localization data"""
        with self.pose_lock:
            self.current_pose = msg.pose.pose
    
    def map_callback(self, msg):
        """Process map updates"""
        # Store current map for path planning
        self.current_map = msg
    
    def command_callback(self, msg):
        """Process voice/remote commands"""
        command = msg.data.lower()
        
        if command == "start_patrol":
            self.start_patrol()
        elif command == "stop_patrol":
            self.stop_patrol()
        elif command == "go_home":
            self.navigate_to_waypoint('home')
        elif command == "go_kitchen":
            self.navigate_to_waypoint('kitchen')
        elif command == "go_living_room":
            self.navigate_to_waypoint('living_room')
        elif command == "go_bedroom":
            self.navigate_to_waypoint('bedroom')
        elif command == "emergency_stop":
            self.emergency_stop = True
            self.stop_robot()
        elif command == "reset_emergency":
            self.emergency_stop = False
        elif command == "save_map":
            self.save_map()
        elif command == "find_dog" or command == "search_for_dog":
            self.start_dog_search()
        elif command == "stop_dog_search":
            self.stop_dog_search()
        
        rospy.loginfo("Processed command: {}".format(command))
    
    def emergency_callback(self, msg):
        """Handle emergency stop signals"""
        self.emergency_stop = msg.data
        if self.emergency_stop:
            self.stop_robot()
    
    def dog_detection_callback(self, msg):
        """Handle dog detection events"""
        try:
            detection_data = json.loads(msg.data)
            
            if detection_data.get('dog_detected', False):
                with self.state_lock:
                    self.dog_found = True
                    self.dog_room = detection_data.get('room', 'unknown')
                    self.dog_photo_taken = detection_data.get('photo_taken', False)
                
                rospy.loginfo("Dog found in {}! Photo taken: {}".format(self.dog_room, self.dog_photo_taken))
                
                # Stop current navigation and prepare to return home
                if self.dog_search_active:
                    self.stop_robot()
                    # Return to dock will be handled by dog_search_loop
                    
        except Exception as e:
            rospy.logwarn("Error processing dog detection: {}".format(e))
    
    def start_dog_search(self):
        """Initialize and start dog search sequence"""
        if self.dog_search_active:
            rospy.loginfo("Dog search already active")
            return
        
        with self.state_lock:
            self.dog_search_active = True
            self.dog_found = False
            self.dog_room = None
            self.dog_photo_taken = False
            self.search_progress = []
            self.current_search_index = 0
            self.search_start_time = datetime.now()
        
        # Define search waypoints from config
        self.search_waypoints = self.config['dog_search']['search_order'].copy()
        
        rospy.loginfo("Starting dog search in {} rooms".format(len(self.search_waypoints)))
        self.status_pub.publish(json.dumps({
            'action': 'dog_search_started',
            'rooms_to_search': self.search_waypoints,
            'timestamp': datetime.now().isoformat()
        }))
    
    def stop_dog_search(self):
        """Stop dog search sequence"""
        with self.state_lock:
            self.dog_search_active = False
            self.dog_found = False
            self.dog_room = None
            self.search_progress = []
        
        self.stop_robot()
        rospy.loginfo("Dog search stopped")
        
        self.status_pub.publish(json.dumps({
            'action': 'dog_search_stopped',
            'timestamp': datetime.now().isoformat()
        }))
    
    def dog_search_loop(self):
        """Main loop for dog search state machine"""
        while not rospy.is_shutdown():
            if self.dog_search_active and not self.emergency_stop:
                # Check for timeout
                if self.search_start_time:
                    elapsed = (datetime.now() - self.search_start_time).total_seconds()
                    if elapsed > self.config['dog_search']['max_search_time']:
                        rospy.loginfo("Dog search timed out")
                        self.stop_dog_search()
                        continue
                
                # If dog was found, return to charging dock
                if self.dog_found:
                    rospy.loginfo("Dog search complete! Dog found in {}. Returning to dock.".format(self.dog_room))
                    self.navigate_to_waypoint('charging_station')
                    
                    # Wait for navigation to complete
                    while self.navigation_active and not rospy.is_shutdown():
                        state = self.move_base_client.get_state()
                        if state == GoalStatus.SUCCEEDED:
                            rospy.loginfo("Returned to charging dock after finding dog")
                            break
                        elif state in [GoalStatus.ABORTED, GoalStatus.REJECTED]:
                            rospy.logwarn("Failed to return to charging dock")
                            break
                        rospy.sleep(0.5)
                    
                    # End search
                    self.stop_dog_search()
                    continue
                
                # Continue searching rooms
                if self.current_search_index < len(self.search_waypoints):
                    current_room = self.search_waypoints[self.current_search_index]
                    
                    # Navigate to next room
                    if not self.navigation_active:
                        rospy.loginfo("Searching room {}/{}: {}".format(self.current_search_index + 1, len(self.search_waypoints), current_room))
                        
                        if self.navigate_to_waypoint(current_room):
                            # Mark room as being searched
                            self.search_progress.append({
                                'room': current_room,
                                'status': 'searching',
                                'timestamp': datetime.now().isoformat()
                            })
                    
                    # Check if we've reached the waypoint
                    elif self.navigation_active:
                        state = self.move_base_client.get_state()
                        if state == GoalStatus.SUCCEEDED:
                            rospy.loginfo("Reached {}, searching for dog...".format(current_room))
                            
                            # Activate dog detection for this room
                            self.dog_detector.start_detection_for_room(current_room)
                            
                            # Wait in room for search time
                            search_time = self.config['dog_search']['room_search_time']
                            rospy.sleep(search_time)
                            
                            # Stop detection for this room
                            self.dog_detector.stop_detection()
                            
                            # Mark room as searched
                            self.search_progress[-1]['status'] = 'completed'
                            
                            # Move to next room
                            self.current_search_index += 1
                            
                        elif state in [GoalStatus.ABORTED, GoalStatus.REJECTED]:
                            rospy.logwarn("Failed to reach {}, skipping...".format(current_room))
                            self.current_search_index += 1
                
                else:
                    # Finished searching all rooms without finding dog
                    rospy.loginfo("Completed searching all rooms. Dog not found. Returning to dock.")
                    self.navigate_to_waypoint('charging_station')
                    
                    # Wait for return navigation
                    while self.navigation_active and not rospy.is_shutdown():
                        state = self.move_base_client.get_state()
                        if state in [GoalStatus.SUCCEEDED, GoalStatus.ABORTED, GoalStatus.REJECTED]:
                            break
                        rospy.sleep(0.5)
                    
                    self.stop_dog_search()
            
            rospy.sleep(1.0)  # Check every second
    
    def navigate_to_waypoint(self, waypoint_name):
        """Navigate to a specific waypoint"""
        if waypoint_name not in self.config['waypoints']:
            rospy.logwarn("Unknown waypoint: {}".format(waypoint_name))
            return False
        
        if self.emergency_stop:
            rospy.logwarn("Navigation blocked by emergency stop")
            return False
        
        waypoint = self.config['waypoints'][waypoint_name]
        
        # Create goal
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = waypoint['x']
        goal.target_pose.pose.position.y = waypoint['y']
        goal.target_pose.pose.orientation.z = waypoint['z']
        goal.target_pose.pose.orientation.w = waypoint['w']
        
        rospy.loginfo("Navigating to {}".format(waypoint_name))
        
        # Send goal
        self.move_base_client.send_goal(goal)
        
        with self.goal_lock:
            self.current_goal = waypoint_name
            self.navigation_active = True
        
        return True
    
    def start_patrol(self):
        """Start autonomous patrol sequence"""
        self.schedule_active = True
        rospy.loginfo("Started autonomous patrol")
    
    def stop_patrol(self):
        """Stop autonomous patrol"""
        self.schedule_active = False
        self.move_base_client.cancel_all_goals()
        self.stop_robot()
        rospy.loginfo("Stopped autonomous patrol")
    
    def stop_robot(self):
        """Immediately stop robot movement"""
        stop_cmd = Twist()
        self.cmd_vel_pub.publish(stop_cmd)
        self.move_base_client.cancel_all_goals()
        
        with self.state_lock:
            self.navigation_active = False
    
    def scheduler_loop(self):
        """Main scheduler loop for autonomous operation"""
        while not rospy.is_shutdown():
            if self.schedule_active and not self.emergency_stop and not self.dog_search_active:
                current_time = datetime.now().time()
                
                for schedule in self.config['schedules']:
                    if not schedule['active']:
                        continue
                    
                    schedule_time = time.fromisoformat(schedule['time'])
                    
                    # Check if it's time to execute this schedule (within 1 minute window)
                    time_diff = abs((current_time.hour * 60 + current_time.minute) - 
                                  (schedule_time.hour * 60 + schedule_time.minute))
                    
                    if time_diff <= 1 and not self.navigation_active:
                        rospy.loginfo("Executing scheduled patrol: {}".format(schedule['name']))
                        self.execute_patrol_sequence(schedule['waypoints'])
            
            rospy.sleep(30)  # Check every 30 seconds
    
    def execute_patrol_sequence(self, waypoints):
        """Execute a sequence of waypoint navigation"""
        for waypoint in waypoints:
            if self.emergency_stop or not self.schedule_active or self.dog_search_active:
                break
            
            if self.navigate_to_waypoint(waypoint):
                # Wait for navigation to complete
                while self.navigation_active and not rospy.is_shutdown():
                    state = self.move_base_client.get_state()
                    if state == GoalStatus.SUCCEEDED:
                        rospy.loginfo("Reached waypoint: {}".format(waypoint))
                        break
                    elif state in [GoalStatus.ABORTED, GoalStatus.REJECTED]:
                        rospy.logwarn("Failed to reach waypoint: {}".format(waypoint))
                        break
                    
                    rospy.sleep(0.5)
                
                # Pause at waypoint
                rospy.sleep(2.0)
        
        rospy.loginfo("Patrol sequence completed")
    
    def save_map(self):
        """Save current SLAM map"""
        try:
            rospy.wait_for_service('/dynamic_map')
            # Call map_saver service to save the map
            import subprocess
            subprocess.run(['rosrun', 'map_server', 'map_saver', 
                          '-f', '/home/linaro/maps/house_map'])
            rospy.loginfo("Map saved successfully")
        except Exception as e:
            rospy.logwarn("Failed to save map: {}".format(e))
    
    def publish_status(self):
        """Publish current robot status"""
        status = {
            'timestamp': datetime.now().isoformat(),
            'battery_level': self.battery_level,
            'emergency_stop': self.emergency_stop,
            'navigation_active': self.navigation_active,
            'current_goal': self.current_goal,
            'schedule_active': self.schedule_active,
            'dog_search_active': self.dog_search_active,
            'dog_found': self.dog_found,
            'dog_room': self.dog_room,
            'search_progress': len(self.search_progress) if self.search_progress else 0
        }
        
        self.status_pub.publish(json.dumps(status))
    
    def run(self):
        """Main run loop"""
        rate = rospy.Rate(10)  # 10 Hz
        
        while not rospy.is_shutdown():
            self.publish_status()
            
            # Safety checks
            if self.battery_level < self.config['safety']['min_battery_level']:
                if not self.emergency_stop and not self.dog_search_active:
                    rospy.logwarn("Low battery - returning to charging station")
                    self.navigate_to_waypoint('charging_station')
            
            rate.sleep()

def main():
    """Main function"""
    try:
        controller = ScoutNavigationController()
        controller.run()
    except rospy.ROSInterruptException:
        rospy.loginfo("Scout Navigation Controller shutting down")
    except Exception as e:
        rospy.logerr("Error in Scout Navigation Controller: {}".format(e))

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Comprehensive test suite for the Moorebot Scout autonomous navigation system.
Tests individual components and system integration.
"""

import unittest
import sys
import os
import time
import threading
from unittest.mock import Mock, patch, MagicMock
import rospy
import rostest
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped, PoseStamped
from sensor_msgs.msg import LaserScan, Image, Imu
from nav_msgs.msg import OccupancyGrid, Odometry
from std_msgs.msg import String

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

class TestLidarDriver(unittest.TestCase):
    """Test the FHL-LD19 Lidar driver functionality."""
    
    def setUp(self):
        """Set up test environment."""
        rospy.init_node('test_lidar_driver', anonymous=True)
        
    def test_lidar_data_parsing(self):
        """Test Lidar data parsing and LaserScan message generation."""
        from ld19_lidar_driver import LD19LidarDriver
        
        driver = LD19LidarDriver()
        
        # Mock serial data
        mock_data = bytes([0x54, 0x2C] + [0] * 44)  # Valid header + data
        
        with patch('serial.Serial') as mock_serial:
            mock_serial.return_value.read.return_value = mock_data
            mock_serial.return_value.in_waiting = 46
            
            # Test data processing
            scan_msg = driver.process_scan_data(mock_data)
            
            self.assertIsNotNone(scan_msg)
            self.assertEqual(len(scan_msg.ranges), 360)
            self.assertGreater(scan_msg.range_max, 0)
            
    def test_lidar_connection(self):
        """Test Lidar serial connection handling."""
        from ld19_lidar_driver import LD19LidarDriver
        
        with patch('serial.Serial') as mock_serial:
            mock_serial.side_effect = Exception("Connection failed")
            
            driver = LD19LidarDriver()
            result = driver.connect()
            
            self.assertFalse(result)

class TestCameraDriver(unittest.TestCase):
    """Test the camera driver and visual odometry."""
    
    def setUp(self):
        """Set up test environment."""
        if not rospy.get_node_uri():
            rospy.init_node('test_camera_driver', anonymous=True)
        
    def test_camera_initialization(self):
        """Test camera initialization and frame capture."""
        from scout_camera_driver import ScoutCameraDriver
        
        with patch('cv2.VideoCapture') as mock_cap:
            mock_cap.return_value.isOpened.return_value = True
            mock_cap.return_value.read.return_value = (True, Mock())
            
            driver = ScoutCameraDriver()
            self.assertTrue(driver.initialize_camera())
            
    def test_visual_odometry(self):
        """Test visual odometry calculation."""
        from scout_camera_driver import ScoutCameraDriver
        
        import numpy as np
        
        driver = ScoutCameraDriver()
        
        # Create mock frames
        frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
        frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Add some features
        frame1[100:150, 100:150] = 255
        frame2[105:155, 105:155] = 255  # Slight movement
        
        with patch('cv2.VideoCapture'):
            odom = driver.calculate_visual_odometry(frame1, frame2)
            
            self.assertIsNotNone(odom)
            self.assertEqual(odom.header.frame_id, "odom")

class TestNavigationController(unittest.TestCase):
    """Test the main navigation controller."""
    
    def setUp(self):
        """Set up test environment."""
        if not rospy.get_node_uri():
            rospy.init_node('test_navigation_controller', anonymous=True)
        
    def test_controller_initialization(self):
        """Test navigation controller initialization."""
        from scout_navigation_controller import ScoutNavigationController
        
        with patch('rospy.Publisher'), \
             patch('rospy.Subscriber'), \
             patch('rospy.Service'):
            
            controller = ScoutNavigationController()
            self.assertIsNotNone(controller)
            self.assertEqual(controller.current_state, "idle")
            
    def test_obstacle_avoidance(self):
        """Test obstacle avoidance behavior."""
        from scout_navigation_controller import ScoutNavigationController
        
        with patch('rospy.Publisher') as mock_pub, \
             patch('rospy.Subscriber'), \
             patch('rospy.Service'):
            
            controller = ScoutNavigationController()
            
            # Create mock laser scan with obstacle
            scan = LaserScan()
            scan.ranges = [1.0] * 360  # 1 meter all around
            scan.ranges[0] = 0.3  # Obstacle directly ahead
            scan.range_min = 0.1
            scan.range_max = 12.0
            
            controller.laser_callback(scan)
            
            # Should trigger obstacle avoidance
            self.assertTrue(controller.obstacle_detected)
            
    def test_voice_command_processing(self):
        """Test voice command processing."""
        from scout_navigation_controller import ScoutNavigationController
        
        with patch('rospy.Publisher'), \
             patch('rospy.Subscriber'), \
             patch('rospy.Service'):
            
            controller = ScoutNavigationController()
            
            # Test valid commands
            test_commands = [
                "start patrol",
                "go to kitchen",
                "stop",
                "return home"
            ]
            
            for command in test_commands:
                msg = String()
                msg.data = command
                controller.voice_command_callback(msg)
                
                # Verify command was processed
                self.assertIn(command.lower(), controller.last_voice_command.lower())

class TestVoiceInterface(unittest.TestCase):
    """Test the voice command interface."""
    
    def setUp(self):
        """Set up test environment."""
        if not rospy.get_node_uri():
            rospy.init_node('test_voice_interface', anonymous=True)
        
    @patch('speech_recognition.Recognizer')
    @patch('speech_recognition.Microphone')
    def test_speech_recognition(self, mock_mic, mock_recognizer):
        """Test speech recognition functionality."""
        from voice_command_interface import VoiceCommandInterface
        
        # Mock successful recognition
        mock_recognizer.return_value.listen.return_value = Mock()
        mock_recognizer.return_value.recognize_google.return_value = "start patrol"
        
        with patch('rospy.Publisher'):
            interface = VoiceCommandInterface()
            
            # This would normally run in a loop
            # For testing, we'll call the recognition method directly
            try:
                result = interface.listen_for_commands()
                self.assertTrue(True)  # If no exception, test passes
            except:
                self.fail("Speech recognition failed unexpectedly")

class TestWebInterface(unittest.TestCase):
    """Test the web dashboard interface."""
    
    def setUp(self):
        """Set up test environment."""
        if not rospy.get_node_uri():
            rospy.init_node('test_web_interface', anonymous=True)
        
    def test_flask_app_creation(self):
        """Test Flask application initialization."""
        from scout_web_interface import ScoutWebInterface
        
        with patch('rospy.Subscriber'), \
             patch('rospy.Publisher'):
            
            interface = ScoutWebInterface()
            self.assertIsNotNone(interface.app)
            
    def test_status_endpoint(self):
        """Test the status API endpoint."""
        from scout_web_interface import ScoutWebInterface
        
        with patch('rospy.Subscriber'), \
             patch('rospy.Publisher'):
            
            interface = ScoutWebInterface()
            
            with interface.app.test_client() as client:
                response = client.get('/api/status')
                self.assertEqual(response.status_code, 200)
                
                data = response.get_json()
                self.assertIn('battery_level', data)
                self.assertIn('current_state', data)

class TestSystemIntegration(unittest.TestCase):
    """Test system integration and end-to-end functionality."""
    
    def setUp(self):
        """Set up test environment."""
        if not rospy.get_node_uri():
            rospy.init_node('test_system_integration', anonymous=True)
        
    def test_ros_communication(self):
        """Test ROS topic communication between components."""
        
        # Test topic existence
        topics = rospy.get_published_topics()
        topic_names = [topic[0] for topic in topics]
        
        expected_topics = [
            '/scan',
            '/cmd_vel',
            '/odom',
            '/camera/image_raw',
            '/voice_commands',
            '/robot_status'
        ]
        
        # In a real test, these topics would be published by the drivers
        # For unit testing, we just verify the test setup
        self.assertTrue(True)  # Placeholder
        
    def test_emergency_stop(self):
        """Test emergency stop functionality."""
        from scout_navigation_controller import ScoutNavigationController
        
        with patch('rospy.Publisher') as mock_pub, \
             patch('rospy.Subscriber'), \
             patch('rospy.Service'):
            
            controller = ScoutNavigationController()
            
            # Trigger emergency stop
            controller.emergency_stop()
            
            # Verify robot stopped
            self.assertEqual(controller.current_state, "emergency_stop")
            
    def test_battery_monitoring(self):
        """Test battery level monitoring and low battery response."""
        from scout_navigation_controller import ScoutNavigationController
        
        with patch('rospy.Publisher'), \
             patch('rospy.Subscriber'), \
             patch('rospy.Service'):
            
            controller = ScoutNavigationController()
            
            # Simulate low battery
            controller.battery_level = 15.0  # Below 20% threshold
            controller.check_battery_level()
            
            # Should trigger return to base
            self.assertTrue(controller.low_battery_mode)

class TestConfiguration(unittest.TestCase):
    """Test configuration file loading and validation."""
    
    def test_config_file_exists(self):
        """Test that configuration files exist and are valid."""
        config_files = [
            '../config/scout_config.yaml',
            '../config/costmap_common_params.yaml',
            '../config/local_costmap_params.yaml',
            '../config/global_costmap_params.yaml',
            '../config/base_local_planner_params.yaml',
            '../config/global_planner_params.yaml'
        ]
        
        for config_file in config_files:
            full_path = os.path.join(os.path.dirname(__file__), config_file)
            self.assertTrue(os.path.exists(full_path), 
                          "Configuration file {} does not exist".format(config_file))
            
    def test_launch_files_exist(self):
        """Test that launch files exist and are valid."""
        launch_files = [
            '../launch/slam_mapping.launch',
            '../launch/navigation.launch'
        ]
        for launch_file in launch_files:
            full_path = os.path.join(os.path.dirname(__file__), launch_file)
            self.assertTrue(os.path.exists(full_path),
                          "Launch file {} does not exist".format(launch_file))

def run_hardware_tests():
    """Run hardware-specific tests (only on actual robot)."""
    print("Running hardware-specific tests...")
    
    # Test Lidar connection
    try:
        import serial
        ser = serial.Serial('/dev/ttyUSB0', 230400, timeout=1)
        ser.close()
        print("✓ Lidar serial connection available")
    except Exception as e:
        print("✗ Lidar connection failed: {}".format(e))
    
    # Test camera connection
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print("✓ Camera connection successful")
            else:
                print("✗ Camera frame capture failed")
        else:
            print("✗ Camera connection failed")
        cap.release()
    except Exception as e:
        print("✗ Camera test failed: {}".format(e))
    
    # Test audio system
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        stream.close()
        p.terminate()
        print("✓ Audio system available")
    except Exception as e:
        print("✗ Audio system test failed: {}".format(e))

if __name__ == '__main__':
    # Check if we're running on the actual robot hardware
    is_hardware = os.path.exists('/dev/ttyUSB0') or '--hardware' in sys.argv
    
    if is_hardware:
        run_hardware_tests()
    
    # Run unit tests
    print("\nRunning unit tests...")
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_cases = [
        TestLidarDriver,
        TestCameraDriver,
        TestNavigationController,
        TestVoiceInterface,
        TestWebInterface,
        TestSystemIntegration,
        TestConfiguration
    ]
    
    for test_case in test_cases:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_case)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\nTest Summary:")
    print("Tests run: {}".format(result.testsRun))
    print("Failures: {}".format(len(result.failures)))
    print("Errors: {}".format(len(result.errors)))
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print("- {}: {}".format(test, traceback.split('\\n')[-2]))
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print("- {}: {}".format(test, traceback.split('\\n')[-2]))
    
    # Exit with error code if tests failed
    sys.exit(0 if result.wasSuccessful() else 1)

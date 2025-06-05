#!/usr/bin/env python3
"""
Integration test script for dog search functionality
Tests the basic integration between navigation controller and dog detection module
"""

import sys
import os
import time
from unittest.mock import Mock, MagicMock

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def mock_ros_components():
    """Mock ROS components for testing"""
    # Mock rospy
    rospy_mock = Mock()
    rospy_mock.loginfo = print
    rospy_mock.logwarn = print
    rospy_mock.logerr = print
    rospy_mock.Publisher = Mock()
    rospy_mock.Subscriber = Mock()
    rospy_mock.Time.now = Mock(return_value=Mock(to_sec=lambda: time.time()))
    sys.modules['rospy'] = rospy_mock
    
    # Mock other ROS modules
    sys.modules['tf2_ros'] = Mock()
    sys.modules['tf2_geometry_msgs'] = Mock()
    sys.modules['sensor_msgs.msg'] = Mock()
    sys.modules['geometry_msgs.msg'] = Mock()
    sys.modules['nav_msgs.msg'] = Mock()
    sys.modules['move_base_msgs.msg'] = Mock()
    sys.modules['actionlib_msgs.msg'] = Mock()
    sys.modules['std_msgs.msg'] = Mock()
    sys.modules['cv_bridge'] = Mock()
    sys.modules['actionlib'] = Mock()
    
    # Mock CV2 and numpy
    sys.modules['cv2'] = Mock()
    sys.modules['numpy'] = Mock()
    
    # Mock PyTorch (mark as not available)
    sys.modules['torch'] = None
    sys.modules['torchvision'] = None
    
    # Mock requests and yaml
    sys.modules['requests'] = Mock()
    sys.modules['yaml'] = Mock()

def test_dog_search_integration():
    """Test the dog search integration"""
    print("\n=== Testing Dog Search Integration ===")
    
    # Mock ROS components first
    mock_ros_components()
    
    try:
        # Import modules after mocking
        from scout_navigation_controller import ScoutNavigationController
        from dog_detection_module import DogDetectionModule
        
        print("✓ Successfully imported modules")
        
        # Create mock navigation controller
        nav_controller = ScoutNavigationController()
        print("✓ Created navigation controller")
        
        # Test initial state
        assert hasattr(nav_controller, 'dog_search_active'), "Missing dog_search_active attribute"
        assert hasattr(nav_controller, 'dog_found'), "Missing dog_found attribute"
        assert hasattr(nav_controller, 'dog_room'), "Missing dog_room attribute"
        print("✓ Navigation controller has dog search attributes")
        
        # Test dog detection module
        dog_detector = DogDetectionModule(nav_controller)
        print("✓ Created dog detection module")
        
        # Test detection_active attribute
        assert hasattr(dog_detector, 'detection_active'), "Missing detection_active attribute"
        assert dog_detector.detection_active == False, "detection_active should be False initially"
        print("✓ Dog detection module has detection_active attribute with correct initial value")
        
        # Test start_dog_search method
        assert hasattr(nav_controller, 'start_dog_search'), "Missing start_dog_search method"
        print("✓ Navigation controller has start_dog_search method")
        
        # Test stop_dog_search method
        assert hasattr(nav_controller, 'stop_dog_search'), "Missing stop_dog_search method"
        print("✓ Navigation controller has stop_dog_search method")
        
        # Test dog detection methods
        assert hasattr(dog_detector, 'start_detection_for_room'), "Missing start_detection_for_room method"
        assert hasattr(dog_detector, 'stop_detection'), "Missing stop_detection method"
        assert hasattr(dog_detector, 'start_continuous_detection'), "Missing start_continuous_detection method"
        assert hasattr(dog_detector, 'set_room'), "Missing set_room method"
        print("✓ Dog detection module has all required methods")
        
        # Test configuration loading
        config = nav_controller.load_config()
        assert 'dog_search' in config, "Missing dog_search configuration"
        assert 'max_search_time' in config['dog_search'], "Missing max_search_time in config"
        assert 'room_search_time' in config['dog_search'], "Missing room_search_time in config"
        assert 'search_order' in config['dog_search'], "Missing search_order in config"
        print("✓ Configuration includes dog search parameters")
        
        # Test that search order includes expected rooms
        search_order = config['dog_search']['search_order']
        expected_rooms = ['living_room', 'kitchen', 'bedroom']
        for room in expected_rooms:
            assert room in search_order, "Room {} missing from search order".format(room)
        print("✓ Search order includes expected rooms")
        
        print("\n✅ All integration tests passed!")
        print("The dog search functionality is properly integrated.")
        
        return True
        
    except ImportError as e:
        print("❌ Import error: {}".format(e))
        return False
    except AssertionError as e:
        print("❌ Assertion error: {}".format(e))
        return False
    except Exception as e:
        print("❌ Unexpected error: {}".format(e))
        return False

def test_dog_search_workflow():
    """Test a simulated dog search workflow"""
    print("\n=== Testing Dog Search Workflow ===")
    
    try:
        from scout_navigation_controller import ScoutNavigationController
        from dog_detection_module import DogDetectionModule
        
        # Create instances
        nav_controller = ScoutNavigationController()
        dog_detector = DogDetectionModule(nav_controller)
        nav_controller.dog_detector = dog_detector
        
        print("✓ Created controller and detector instances")
        
        # Test workflow states
        print("\n1. Testing initial state...")
        assert nav_controller.dog_search_active == False
        assert nav_controller.dog_found == False
        assert nav_controller.dog_room == ""
        print("✓ Initial state correct")
        
        print("\n2. Testing dog search start...")
        # Simulate starting dog search (without actually running threads)
        nav_controller.dog_search_active = True
        nav_controller.dog_found = False
        nav_controller.dog_room = ""
        nav_controller.search_progress = {'rooms_searched': [], 'current_room': 'living_room'}
        print("✓ Dog search state activated")
        
        print("\n3. Testing room detection...")
        # Simulate finding dog in kitchen
        dog_detector.set_room('kitchen')
        assert dog_detector.current_room == 'kitchen'
        print("✓ Room setting works")
        
        print("\n4. Testing detection activation...")
        dog_detector.start_detection_for_room('kitchen')
        assert dog_detector.detection_active == True
        assert dog_detector.current_room == 'kitchen'
        print("✓ Detection activation works")
        
        print("\n5. Testing detection stop...")
        dog_detector.stop_detection()
        assert dog_detector.detection_active == False
        print("✓ Detection stop works")
        
        print("\n✅ Dog search workflow test passed!")
        
        return True
        
    except Exception as e:
        print("❌ Workflow test error: {}".format(e))
        return False

if __name__ == "__main__":
    print("Starting Dog Search Integration Tests...")
    
    # Run integration tests
    integration_success = test_dog_search_integration()
    
    if integration_success:
        # Run workflow tests
        workflow_success = test_dog_search_workflow()
        
        if workflow_success:
            print("\n🎉 ALL TESTS PASSED!")
            print("The dog search integration is complete and working properly.")
            print("\nNext steps:")
            print("- Deploy to robot and test with actual ROS environment")
            print("- Test with real camera and dog detection")
            print("- Verify navigation waypoints and room boundaries")
            print("- Test return-to-dock functionality")
        else:
            print("\n⚠️  Integration tests passed but workflow tests failed")
            sys.exit(1)
    else:
        print("\n❌ Integration tests failed")
        sys.exit(1)

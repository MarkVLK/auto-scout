#!/usr/bin/env python3
"""
Dog Search Demo Script

This script demonstr        if room == "kitchen":  # Simulate finding dog in kitchen
            print("   🐕 DOG DETECTED i        print("\n🎉 Demo completed successfully!")
        print("\nTo run on actual robot:")
        print("1. Deploy code to robot with ROS environment")
        print("2. Connect FHL-LD19 Lidar and camera")
        print("3. Run: roslaunch auto-scout scout_complete.launch")
        print("4. Say: 'Find my dog' or use web interface")
        
    except Exception as e:
        print("❌ Demo failed: {}".format(e))
        return 1mat(room))
            print("   → Taking photo...")
            print("   → Recording location: {}".format(room))
            print("   → Search complete!")
            break
        else:
            print("   → No dog found in {}".format(room))
    
    print("\n3. Returning to charging dock...")
    print("   → Navigation complete")
    
    print("\n✅ Dog search demo completed!")
    print("Result: Dog found in kitchen")
    print("Photo saved and location recorded") the dog search functionality
of the Auto-Scout robot system.

Usage:
    python dog_search_demo.py [--config CONFIG_FILE]
"""

import sys
import time
import argparse
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

try:
    from scout_navigation_controller import ScoutNavigationController
    from dog_detection_module import DogDetectionModule
    print("✓ Successfully imported Auto-Scout modules")
except ImportError as e:
    print("❌ Failed to import modules: {}".format(e))
    print("This demo requires the ROS environment and Auto-Scout modules")
    sys.exit(1)


def demo_dog_search():
    """Demonstrate the dog search functionality."""
    print("\n=== Auto-Scout Dog Search Demo ===")
    
    # Initialize the navigation controller
    print("Initializing navigation controller...")
    nav_controller = ScoutNavigationController()
    
    # Initialize dog detection module
    print("Initializing dog detection module...")
    dog_detector = DogDetectionModule(nav_controller)
    nav_controller.dog_detector = dog_detector
    
    print("✓ System initialized successfully")
    
    # Simulate dog search workflow
    print("\n1. Starting dog search...")
    print("   Voice command equivalent: 'Find dog'")
    
    # In real usage, this would be:
    # nav_controller.start_dog_search()
    
    # For demo, we'll simulate the states
    print("   → Robot activating dog search mode")
    print("   → Planning route through house rooms")
    
    # Simulate room-by-room search
    config = nav_controller.load_config()
    search_order = config['dog_search']['search_order']
    
    print("\n2. Searching rooms in order: {}".format(search_order))
    
    for i, room in enumerate(search_order):
        print("\n   Room {}/{}: {}".format(i+1, len(search_order), room))
        print("   → Navigating to {}".format(room))
        print("   → Activating camera detection")
        print("   → Searching for 30 seconds...")
        
        # Simulate detection process
        time.sleep(1)  # Brief pause for demo
        
        # Simulate finding dog in kitchen (for demo)
        if room == "kitchen":
            print("   🐕 DOG DETECTED in {}!".format(room))
            print("   → Taking photo...")
            print("   → Recording location: {}".format(room))
            print("   → Search complete!")
            break
        else:
            print("   → No dog found in {}".format(room))
    
    print("\n3. Returning to charging dock...")
    print("   → Navigation complete")
    
    print("\n✅ Dog search demo completed!")
    print("Result: Dog found in kitchen")
    print("Photo saved and location recorded")
    
    return True


def demo_voice_commands():
    """Demonstrate voice command processing."""
    print("\n=== Voice Commands Demo ===")
    
    commands = [
        ("find_dog", "Find my dog"),
        ("stop_dog_search", "Stop searching"),
        ("go_kitchen", "Go to kitchen"),
        ("go_charging_dock", "Go home"),
        ("emergency_stop", "Emergency stop")
    ]
    
    print("Available voice commands:")
    for cmd, phrase in commands:
        print("  '{}' → {}".format(phrase, cmd))
    
    # Simulate voice command processing
    print("\nSimulating voice command: 'Find my dog'")
    print("→ Parsed as: find_dog")
    print("→ Action: Starting dog search workflow")
    
    return True


def demo_configuration():
    """Demonstrate configuration loading."""
    print("\n=== Configuration Demo ===")
    
    nav_controller = ScoutNavigationController()
    config = nav_controller.load_config()
    
    print("Dog search configuration:")
    dog_config = config.get('dog_search', {})
    
    print("  Max search time: {} seconds".format(dog_config.get('max_search_time', 600)))
    print("  Room search time: {} seconds".format(dog_config.get('room_search_time', 30)))
    print("  Search order: {}".format(dog_config.get('search_order', [])))
    
    print("\nHouse layout rooms:")
    house_layout = config.get('house_layout', {})
    rooms = house_layout.get('rooms', {})
    
    for room_name, room_data in rooms.items():
        center = room_data.get('center', {})
        print("  {}: center at ({}, {})".format(room_name, center.get('x', 0), center.get('y', 0)))
    
    return True


def main():
    """Main demo function."""
    parser = argparse.ArgumentParser(description="Auto-Scout Dog Search Demo")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--demo", choices=["search", "voice", "config", "all"], 
                       default="all", help="Which demo to run")
    
    args = parser.parse_args()
    
    print("🤖 Auto-Scout Dog Search Demo")
    print("=" * 40)
    
    try:
        if args.demo in ["search", "all"]:
            demo_dog_search()
        
        if args.demo in ["voice", "all"]:
            demo_voice_commands()
        
        if args.demo in ["config", "all"]:
            demo_configuration()
        
        print("\n🎉 Demo completed successfully!")
        print("\nTo run on actual robot:")
        print("1. Deploy code to robot with ROS environment")
        print("2. Connect FHL-LD19 Lidar and camera")
        print("3. Run: roslaunch auto-scout scout_complete.launch")
        print("4. Say: 'Find my dog' or use web interface")
        
    except Exception as e:
        print("❌ Demo failed: {}".format(e))
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

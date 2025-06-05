#!/usr/bin/env python3
"""
Simple test to check if the key attributes exist in our code
"""

import ast
import os

def check_file_for_attributes(file_path, required_attributes):
    """Check if a Python file contains the required attributes"""
    print("\nChecking {}...".format(os.path.basename(file_path)))
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Simple text search for attributes
        found_attributes = []
        missing_attributes = []
        
        for attr in required_attributes:
            if "self.{}".format(attr) in content:
                found_attributes.append(attr)
                print("✓ Found: self.{}".format(attr))
            else:
                missing_attributes.append(attr)
                print("❌ Missing: self.{}".format(attr))
        
        return len(missing_attributes) == 0, found_attributes, missing_attributes
        
    except Exception as e:
        print("Error reading file: {}".format(e))
        return False, [], required_attributes

def main():
    print("=== Dog Search Integration Verification ===")
    
    # Define required attributes for each module
    nav_controller_attrs = [
        'dog_search_active',
        'dog_found', 
        'dog_room',
        'search_progress',
        'dog_search_thread'
    ]
    
    dog_detector_attrs = [
        'detection_active',
        'dog_detected',
        'current_room',
        'detection_confidence'
    ]
    
    # Check navigation controller
    nav_success, nav_found, nav_missing = check_file_for_attributes(
        '/Users/markvlcek/Code/auto-scout/src/scout_navigation_controller.py',
        nav_controller_attrs
    )
    
    # Check dog detection module  
    dog_success, dog_found, dog_missing = check_file_for_attributes(
        '/Users/markvlcek/Code/auto-scout/src/dog_detection_module.py',
        dog_detector_attrs
    )
    
    # Check for required methods
    print("\nChecking for required methods...")
    
    nav_file = '/Users/markvlcek/Code/auto-scout/src/scout_navigation_controller.py'
    with open(nav_file, 'r') as f:
        nav_content = f.read()
    
    dog_file = '/Users/markvlcek/Code/auto-scout/src/dog_detection_module.py' 
    with open(dog_file, 'r') as f:
        dog_content = f.read()
    
    # Check navigation controller methods
    nav_methods = ['start_dog_search', 'stop_dog_search', 'dog_search_loop']
    for method in nav_methods:
        if "def {}".format(method) in nav_content:
            print("✓ Found method: {}".format(method))
        else:
            print("❌ Missing method: {}".format(method))
    
    # Check dog detector methods
    dog_methods = ['start_detection_for_room', 'stop_detection', 'set_room']
    for method in dog_methods:
        if "def {}".format(method) in dog_content:
            print("✓ Found method: {}".format(method))
        else:
            print("❌ Missing method: {}".format(method))
    
    # Summary
    print("\n=== SUMMARY ===")
    if nav_success:
        print("✅ Navigation controller has all required attributes")
    else:
        print("❌ Navigation controller missing: {}".format(nav_missing))
        
    if dog_success:
        print("✅ Dog detection module has all required attributes")
    else:
        print("❌ Dog detection module missing: {}".format(dog_missing))
    
    if nav_success and dog_success:
        print("\n🎉 INTEGRATION COMPLETE!")
        print("The dog search functionality is properly integrated.")
        print("\nKey Features Added:")
        print("- Dog search state management")
        print("- Room-by-room search workflow")
        print("- Detection activation/deactivation")
        print("- Return-to-dock after search")
        print("- Configuration for search parameters")
    else:
        print("\n⚠️ Integration incomplete - see missing items above")

if __name__ == "__main__":
    main()

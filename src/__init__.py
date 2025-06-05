"""
Auto-Scout: Autonomous Navigation System for Moorebot Scout

This package provides autonomous navigation capabilities for the Moorebot Scout robot
using the FHL-LD19 Lidar sensor, including dog detection and search functionality.

Main modules:
- scout_navigation_controller: Core navigation and control logic
- dog_detection_module: Computer vision-based dog detection
- ld19_lidar_driver: Lidar sensor interface
- scout_camera_driver: Camera interface and processing
- scout_web_interface: Web-based control dashboard
- voice_command_interface: Voice command processing

Author: Auto-Scout Development Team
License: MIT
"""

__version__ = "1.1.0"
__author__ = "Auto-Scout Development Team"
__license__ = "MIT"

# Import main classes for easy access
from .scout_navigation_controller import ScoutNavigationController
from .dog_detection_module import DogDetectionModule
from .ld19_lidar_driver import LD19LidarDriver
from .scout_camera_driver import ScoutCameraDriver
from .scout_web_interface import ScoutWebInterface
from .voice_command_interface import VoiceCommandInterface

__all__ = [
    'ScoutNavigationController',
    'DogDetectionModule', 
    'LD19LidarDriver',
    'ScoutCameraDriver',
    'ScoutWebInterface',
    'VoiceCommandInterface'
]

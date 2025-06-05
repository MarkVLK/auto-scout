#!/usr/bin/env python3
"""
Scout Hardware Compatibility Checker
Tests compatibility with Debian Stretch + ROS Melodic + ARM64
"""

import sys
import platform
import subprocess
import os
from pathlib import Path

def check_system_info():
    """Check basic system compatibility"""
    print("🤖 Scout Hardware Compatibility Check")
    print("=" * 50)
    
    # System information
    print(f"Platform: {platform.platform()}")
    print(f"Architecture: {platform.machine()}")
    print(f"Python Version: {sys.version}")
    
    # Check if we're on the expected system
    is_arm64 = platform.machine() in ['aarch64', 'arm64']
    is_linux = platform.system() == 'Linux'
    python_version = sys.version_info
    
    if is_arm64 and is_linux:
        print("✅ Running on ARM64 Linux (Scout compatible)")
    else:
        print("⚠️  Not running on Scout hardware")
    
    if python_version >= (3, 5):
        print(f"✅ Python {python_version.major}.{python_version.minor} is compatible")
    else:
        print(f"❌ Python {python_version.major}.{python_version.minor} is too old")
        return False
    
    return True

def check_ros_melodic():
    """Check ROS Melodic installation and packages"""
    print("\n🐢 ROS Melodic Compatibility")
    print("-" * 30)
    
    try:
        # Check ROS distro
        result = subprocess.run(['rosversion', '-d'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            distro = result.stdout.strip()
            print(f"ROS Distribution: {distro}")
            if distro == 'melodic':
                print("✅ ROS Melodic detected")
            else:
                print(f"⚠️  Expected melodic, found {distro}")
        else:
            print("❌ ROS not found or not configured")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ ROS commands not available")
        return False
    
    # Check critical ROS packages
    required_packages = [
        'move_base',
        'gmapping', 
        'amcl',
        'map_server',
        'navigation',
        'tf2_ros'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            result = subprocess.run(['rospack', 'find', package], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                print(f"✅ {package}: Found")
            else:
                print(f"❌ {package}: Missing")
                missing_packages.append(package)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(f"⚠️  Cannot check {package}")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n❌ Missing packages: {', '.join(missing_packages)}")
        print("Install with: sudo apt install ros-melodic-<package-name>")
        return False
    
    return True

def check_python_dependencies():
    """Check if Python dependencies can be installed"""
    print("\n🐍 Python Dependencies Check")
    print("-" * 30)
    
    # Critical dependencies for ARM64/Debian Stretch
    critical_deps = [
        ('numpy', '1.16.0'),
        ('opencv-python', '4.1.0'),
        ('PyYAML', '5.1.0'),
        ('requests', '2.20.0'),
        ('flask', '1.0.0'),
        ('pillow', '6.0.0'),
    ]
    
    failed_imports = []
    for package, min_version in critical_deps:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package}: Available")
        except ImportError:
            print(f"⚠️  {package}: Not installed (install with pip)")
            failed_imports.append(package)
    
    if failed_imports:
        print(f"\nInstall missing packages:")
        print(f"pip3 install {' '.join(failed_imports)}")
    
    return len(failed_imports) == 0

def check_hardware_access():
    """Check access to Scout hardware interfaces"""
    print("\n🔧 Hardware Access Check")
    print("-" * 30)
    
    # Check for common hardware interfaces
    hardware_checks = [
        ('/dev/ttyUSB0', 'USB Serial (Lidar)'),
        ('/dev/ttyACM0', 'ACM Serial (Arduino)'),
        ('/dev/video0', 'Camera Device'),
        ('/sys/class/gpio', 'GPIO Access'),
    ]
    
    for device_path, description in hardware_checks:
        if os.path.exists(device_path):
            print(f"✅ {description}: Available at {device_path}")
        else:
            print(f"⚠️  {description}: Not found at {device_path}")
    
    # Check if user is in dialout group (for serial access)
    try:
        result = subprocess.run(['groups'], capture_output=True, text=True)
        groups = result.stdout.strip()
        if 'dialout' in groups:
            print("✅ User in dialout group (serial access)")
        else:
            print("⚠️  User not in dialout group")
            print("   Add with: sudo usermod -a -G dialout $USER")
    except:
        print("⚠️  Cannot check user groups")
    
    return True

def check_installation_method():
    """Suggest best installation method for Scout"""
    print("\n📦 Recommended Installation")
    print("-" * 30)
    
    print("For Scout deployment, use:")
    print("1. Install system ROS packages:")
    print("   sudo apt update")
    print("   sudo apt install ros-melodic-navigation ros-melodic-gmapping")
    print("   sudo apt install ros-melodic-tf2-tools ros-melodic-robot-localization")
    print("")
    print("2. Install Python dependencies:")
    print("   pip3 install --user -e .")
    print("   # or for development:")
    print("   pip3 install --user -e .[dev]")
    print("")
    print("3. Set up environment:")
    print("   echo 'source /opt/ros/melodic/setup.bash' >> ~/.bashrc")
    print("   source ~/.bashrc")

def main():
    """Run all compatibility checks"""
    
    all_passed = True
    
    # System checks
    if not check_system_info():
        all_passed = False
    
    # ROS checks  
    if not check_ros_melodic():
        all_passed = False
    
    # Python dependency checks
    if not check_python_dependencies():
        # This is not critical - dependencies can be installed
        pass
    
    # Hardware access checks
    check_hardware_access()
    
    # Installation recommendations
    check_installation_method()
    
    # Final summary
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 Scout is ready for auto-scout installation!")
    else:
        print("⚠️  Some issues found - see recommendations above")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

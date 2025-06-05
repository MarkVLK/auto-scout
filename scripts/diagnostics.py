#!/usr/bin/env python3
"""
Comprehensive diagnostic script for the Moorebot Scout autonomous navigation system.
Checks hardware, software, and system configuration.
"""

import os
import sys
import subprocess
import time
import json
from datetime import datetime
import psutil
import yaml

class ScoutDiagnostics:
    def __init__(self):
        """Initialize diagnostics."""
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'system': {},
            'hardware': {},
            'software': {},
            'ros': {},
            'services': {},
            'network': {},
            'issues': [],
            'recommendations': []
        }
        
    def run_all_diagnostics(self):
        """Run all diagnostic tests."""
        print("🔍 Running Moorebot Scout Diagnostics")
        print("=" * 50)
        
        self.check_system_info()
        self.check_hardware()
        self.check_software_dependencies()
        self.check_ros_environment()
        self.check_services()
        self.check_network()
        self.check_project_files()
        self.check_permissions()
        
        self.generate_report()
        
    def check_system_info(self):
        """Check basic system information."""
        print("\n📊 System Information")
        print("-" * 20)
        
        try:
            # Basic system info
            import platform
            self.results['system'] = {
                'os': platform.system(),
                'os_version': platform.release(),
                'architecture': platform.machine(),
                'hostname': platform.node(),
                'python_version': platform.python_version(),
                'cpu_count': psutil.cpu_count(),
                'memory_total': psutil.virtual_memory().total,
                'memory_available': psutil.virtual_memory().available,
                'disk_usage': psutil.disk_usage('/').percent
            }
            
            print("✓ OS: {} {}".format(self.results['system']['os'], self.results['system']['os_version']))
            print("✓ Architecture: {}".format(self.results['system']['architecture']))
            print("✓ Python: {}".format(self.results['system']['python_version']))
            print("✓ CPU cores: {}".format(self.results['system']['cpu_count']))
            print("✓ Memory: {:.1f}GB available".format(self.results['system']['memory_available']/1024**3))
            print("✓ Disk usage: {:.1f}%".format(self.results['system']['disk_usage']))
            
            if self.results['system']['disk_usage'] > 85:
                self.results['issues'].append("High disk usage")
                self.results['recommendations'].append("Free up disk space")
                
        except Exception as e:
            print("✗ System info check failed: {}".format(e))
            self.results['issues'].append("System info error: {}".format(e))
            
    def check_hardware(self):
        """Check hardware connectivity."""
        print("\n🔧 Hardware Check")
        print("-" * 17)
        
        hardware_status = {}
        
        # Check Lidar (USB serial device)
        lidar_ports = ['/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyACM0']
        lidar_found = False
        
        for port in lidar_ports:
            if os.path.exists(port):
                try:
                    import serial
                    ser = serial.Serial(port, 230400, timeout=1)
                    ser.close()
                    hardware_status['lidar'] = {'port': port, 'status': 'connected'}
                    print("✓ Lidar found on {}".format(port))
                    lidar_found = True
                    break
                except Exception as e:
                    hardware_status['lidar'] = {'port': port, 'status': 'error', 'error': str(e)}
                    
        if not lidar_found:
            print("✗ Lidar not found")
            hardware_status['lidar'] = {'status': 'not_found'}
            self.results['issues'].append("Lidar not detected")
            self.results['recommendations'].append("Check Lidar USB connection")
            
        # Check camera
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    hardware_status['camera'] = {'status': 'working', 'resolution': "{}x{}".format(frame.shape[1], frame.shape[0])}
                    print("✓ Camera working ({}x{})".format(frame.shape[1], frame.shape[0]))
                else:
                    hardware_status['camera'] = {'status': 'no_frame'}
                    print("✗ Camera connected but no frame")
                    self.results['issues'].append("Camera not providing frames")
            else:
                hardware_status['camera'] = {'status': 'not_found'}
                print("✗ Camera not found")
                self.results['issues'].append("Camera not detected")
            cap.release()
        except Exception as e:
            hardware_status['camera'] = {'status': 'error', 'error': str(e)}
            print("✗ Camera error: {}".format(e))
            self.results['issues'].append("Camera error: {}".format(e))
            
        # Check audio
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            
            # Check input devices
            input_devices = []
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    input_devices.append(info['name'])
                    
            # Check output devices  
            output_devices = []
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:
                    output_devices.append(info['name'])
                    
            p.terminate()
            
            hardware_status['audio'] = {
                'status': 'available',
                'input_devices': len(input_devices),
                'output_devices': len(output_devices)
            }
            print("✓ Audio: {} input, {} output devices".format(len(input_devices), len(output_devices)))
            
        except Exception as e:
            hardware_status['audio'] = {'status': 'error', 'error': str(e)}
            print("✗ Audio error: {}".format(e))
            self.results['issues'].append("Audio system error: {}".format(e))
            
        self.results['hardware'] = hardware_status
        
    def check_software_dependencies(self):
        """Check required software packages."""
        print("\n📦 Software Dependencies")
        print("-" * 24)
        
        dependencies = {
            'python_packages': [
                'rospy', 'cv2', 'numpy', 'scipy', 'flask', 'flask_socketio',
                'speech_recognition', 'pyttsx3', 'pyaudio', 'serial', 'yaml',
                'tf', 'tf2_ros', 'geometry_msgs', 'sensor_msgs', 'nav_msgs'
            ],
            'system_packages': [
                'roscore', 'roslaunch', 'rostopic', 'rosnode'
            ]
        }
        
        software_status = {'python_packages': {}, 'system_packages': {}}
        
        # Check Python packages
        for package in dependencies['python_packages']:
            try:
                __import__(package)
                software_status['python_packages'][package] = 'installed'
                print("✓ {}".format(package))
            except ImportError:
                software_status['python_packages'][package] = 'missing'
                print("✗ {} (missing)".format(package))
                self.results['issues'].append("Missing Python package: {}".format(package))
                self.results['recommendations'].append("Install {}: pip install {}".format(package, package))
                
        # Check system packages
        for package in dependencies['system_packages']:
            try:
                result = subprocess.run(['which', package], capture_output=True, text=True)
                if result.returncode == 0:
                    software_status['system_packages'][package] = 'installed'
                    print("✓ {}".format(package))
                else:
                    software_status['system_packages'][package] = 'missing'
                    print("✗ {} (missing)".format(package))
                    self.results['issues'].append("Missing system package: {}".format(package))
            except Exception as e:
                software_status['system_packages'][package] = 'error'
                print("✗ {} (error: {})".format(package, e))
                
        self.results['software'] = software_status
        
    def check_ros_environment(self):
        """Check ROS installation and environment."""
        print("\n🤖 ROS Environment")
        print("-" * 18)
        
        ros_status = {}
        
        # Check ROS installation
        ros_distro = os.environ.get('ROS_DISTRO')
        if ros_distro:
            ros_status['distro'] = ros_distro
            print("✓ ROS {} detected".format(ros_distro))
        else:
            ros_status['distro'] = None
            print("✗ ROS_DISTRO not set")
            self.results['issues'].append("ROS environment not configured")
            self.results['recommendations'].append("Source ROS setup.bash")
            
        # Check ROS paths
        ros_package_path = os.environ.get('ROS_PACKAGE_PATH')
        if ros_package_path:
            ros_status['package_path'] = ros_package_path
            print("✓ ROS_PACKAGE_PATH set")
        else:
            ros_status['package_path'] = None
            print("✗ ROS_PACKAGE_PATH not set")
            
        # Check if roscore is running
        try:
            result = subprocess.run(['rostopic', 'list'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ros_status['roscore'] = 'running'
                print("✓ roscore is running")
                
                # List active topics
                topics = result.stdout.strip().split('\n')
                ros_status['active_topics'] = len(topics)
                print("✓ {} active topics".format(len(topics)))
                
            else:
                ros_status['roscore'] = 'not_running'
                print("✗ roscore not running")
                self.results['issues'].append("roscore not running")
                self.results['recommendations'].append("Start roscore")
                
        except subprocess.TimeoutExpired:
            ros_status['roscore'] = 'timeout'
            print("✗ rostopic command timeout")
            self.results['issues'].append("ROS communication timeout")
            
        except Exception as e:
            ros_status['roscore'] = 'error'
            print("✗ ROS check error: {}".format(e))
            
        self.results['ros'] = ros_status
        
    def check_services(self):
        """Check systemd services."""
        print("\n🚀 System Services")
        print("-" * 18)
        
        services = ['scout-navigation', 'scout-web']
        service_status = {}
        
        for service in services:
            try:
                result = subprocess.run(['systemctl', 'is-active', service], 
                                      capture_output=True, text=True)
                status = result.stdout.strip()
                service_status[service] = status
                
                if status == 'active':
                    print("✓ {} service running".format(service))
                else:
                    print("✗ {} service {}".format(service, status))
                    if status != 'inactive':
                        self.results['issues'].append("{} service not running".format(service))
                        
            except Exception as e:
                service_status[service] = 'error'
                print("✗ {} service check error: {}".format(service, e))
                
        self.results['services'] = service_status
        
    def check_network(self):
        """Check network connectivity."""
        print("\n🌐 Network Connectivity")
        print("-" * 22)
        
        network_status = {}
        
        # Check internet connectivity
        try:
            result = subprocess.run(['ping', '-c', '1', '8.8.8.8'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                network_status['internet'] = 'connected'
                print("✓ Internet connectivity")
            else:
                network_status['internet'] = 'disconnected'
                print("✗ No internet connectivity")
                self.results['issues'].append("No internet connection")
                
        except Exception as e:
            network_status['internet'] = 'error'
            print("✗ Internet check error: {}".format(e))
            
        # Check local network interfaces
        try:
            interfaces = psutil.net_if_addrs()
            active_interfaces = []
            
            for interface, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == 2 and not addr.address.startswith('127.'):  # IPv4, not localhost
                        active_interfaces.append({
                            'interface': interface,
                            'ip': addr.address
                        })
                        
            network_status['interfaces'] = active_interfaces
            print("✓ {} active network interfaces".format(len(active_interfaces)))
            
            for iface in active_interfaces:
                print("  - {}: {}".format(iface['interface'], iface['ip']))
                
        except Exception as e:
            print("✗ Network interface check error: {}".format(e))
            
        self.results['network'] = network_status
        
    def check_project_files(self):
        """Check project file structure."""
        print("\n📁 Project Files")
        print("-" * 16)
        
        project_root = os.path.dirname(os.path.dirname(__file__))
        
        required_files = [
            'src/scout_navigation_controller.py',
            'src/ld19_lidar_driver.py',
            'src/scout_camera_driver.py',
            'src/voice_command_interface.py',
            'src/scout_web_interface.py',
            'launch/slam_mapping.launch',
            'launch/navigation.launch',
            'config/scout_config.yaml',
            'urdf/scout.urdf',
            'install.sh'
        ]
        
        file_status = {}
        
        for file_path in required_files:
            full_path = os.path.join(project_root, file_path)
            if os.path.exists(full_path):
                file_status[file_path] = 'exists'
                print("✓ {}".format(file_path))
            else:
                file_status[file_path] = 'missing'
                print("✗ {} (missing)".format(file_path))
                self.results['issues'].append("Missing file: {}".format(file_path))
                
        self.results['project_files'] = file_status
        
    def check_permissions(self):
        """Check file permissions."""
        print("\n🔐 File Permissions")
        print("-" * 18)
        
        project_root = os.path.dirname(os.path.dirname(__file__))
        
        executable_files = [
            'install.sh',
            'scripts/calibrate_camera.py',
            'scripts/diagnostics.py'
        ]
        
        permission_status = {}
        
        for file_path in executable_files:
            full_path = os.path.join(project_root, file_path)
            if os.path.exists(full_path):
                if os.access(full_path, os.X_OK):
                    permission_status[file_path] = 'executable'
                    print("✓ {} (executable)".format(file_path))
                else:
                    permission_status[file_path] = 'not_executable'
                    print("✗ {} (not executable)".format(file_path))
                    self.results['issues'].append("File not executable: {}".format(file_path))
                    self.results['recommendations'].append("chmod +x {}".format(file_path))
            else:
                permission_status[file_path] = 'missing'
                
        self.results['permissions'] = permission_status
        
    def generate_report(self):
        """Generate diagnostic report."""
        print("\n" + "=" * 50)
        print("📋 DIAGNOSTIC REPORT")
        print("=" * 50)
        
        # Summary
        total_issues = len(self.results['issues'])
        if total_issues == 0:
            print("✅ All systems operational!")
        else:
            print("⚠️  {} issue(s) found".format(total_issues))
            
        # Issues
        if self.results['issues']:
            print("\n🚨 Issues Found:")
            for i, issue in enumerate(self.results['issues'], 1):
                print("  {}. {}".format(i, issue))
                
        # Recommendations
        if self.results['recommendations']:
            print("\n💡 Recommendations:")
            for i, rec in enumerate(self.results['recommendations'], 1):
                print("  {}. {}".format(i, rec))
                
        # Save detailed report
        report_file = "diagnostic_report_{}.json".format(datetime.now().strftime('%Y%m%d_%H%M%S'))
        report_path = os.path.join(os.path.dirname(__file__), '..', 'logs', report_file)
        
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
            
        print("\n📄 Detailed report saved: {}".format(report_path))
        
        # System health score
        total_checks = sum([
            len(self.results['hardware']),
            len(self.results['software']['python_packages']),
            len(self.results['software']['system_packages']),
            len(self.results['project_files']),
            3  # ROS, services, network base checks
        ])
        
        failed_checks = len(self.results['issues'])
        health_score = max(0, (total_checks - failed_checks) / total_checks * 100)
        
        print("\n📊 System Health Score: {:.1f}%".format(health_score))
        
        if health_score >= 90:
            print("🟢 Excellent - System ready for deployment")
        elif health_score >= 70:
            print("🟡 Good - Minor issues to address")
        elif health_score >= 50:
            print("🟠 Fair - Several issues need attention")
        else:
            print("🔴 Poor - Major issues require immediate attention")

def main():
    """Main diagnostic function."""
    try:
        diagnostics = ScoutDiagnostics()
        diagnostics.run_all_diagnostics()
        
    except KeyboardInterrupt:
        print("\n\nDiagnostics interrupted by user")
    except Exception as e:
        print("\nDiagnostic error: {}".format(e))
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()

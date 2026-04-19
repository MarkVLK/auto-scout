#!/usr/bin/env python3
"""LiDAR driver for an LD19-class scanner."""

import rospy
import serial
import struct
import math
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Header

from config_utils import load_scout_config

class LD19LidarDriver:
    """
    Driver for the youyeetoo FHL-LD19 Lidar sensor
    """
    
    def __init__(self):
        from auto_scout.site_config import load_site_config, scout_runtime_device, scout_runtime_topic

        rospy.init_node('ld19_lidar_driver', anonymous=True)

        config_path = rospy.get_param('~config_file', None)
        site_path = rospy.get_param('~site_file', None)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        if not isinstance(self.config, dict):
            self.config = {}

        lidar_config = self.config.get('lidar', {})

        self.port = rospy.get_param(
            '~port',
            scout_runtime_device(self.site_config, self.config, 'lidar', lidar_config.get('port', '/dev/ttyUSB0')),
        )
        self.baudrate = rospy.get_param('~baudrate', lidar_config.get('baudrate', 230400))
        self.frame_id = rospy.get_param('~frame_id', lidar_config.get('frame_id', 'base_laser'))
        self.angle_min = rospy.get_param('~angle_min', lidar_config.get('angle_min', 0.0))
        self.angle_max = rospy.get_param('~angle_max', lidar_config.get('angle_max', 2 * math.pi))
        self.range_min = rospy.get_param('~range_min', lidar_config.get('range_min', 0.02))
        self.range_max = rospy.get_param('~range_max', lidar_config.get('range_max', 12.0))
        self.invert_scan = rospy.get_param('~invert_scan', lidar_config.get('invert_scan', False))
        self.scan_topic = rospy.get_param(
            '~scan_topic',
            scout_runtime_topic(self.site_config, self.config, 'lidar_scan', '/scan'),
        )

        self.scan_pub = rospy.Publisher(self.scan_topic, LaserScan, queue_size=1)
        
        # Initialize serial connection
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            rospy.loginfo("Connected to LD19 Lidar on {} at {} baud".format(self.port, self.baudrate))
        except Exception as e:
            rospy.logerr("Failed to connect to Lidar: {}".format(e))
            return
        
        # Scan data buffer
        self.scan_data = {}
        self.last_scan_time = rospy.Time.now()
        
        rospy.loginfo(
            "LD19 lidar driver initialized (config: {}, topic: {})".format(
                self.config_path or "defaults",
                self.scan_topic,
            )
        )
    
    def parse_packet(self, packet):
        """Parse a single Lidar data packet"""
        if len(packet) < 47:  # Minimum packet size
            return None
        
        # Check packet header
        if packet[0] != 0x54:
            return None
        
        # Extract packet data
        packet_type = packet[1]
        packet_length = packet[2]
        
        if packet_type == 0x2C:  # Point cloud data packet
            # Extract scan data
            speed = struct.unpack('<H', packet[3:5])[0]  # Speed in degrees per second
            start_angle = struct.unpack('<H', packet[5:7])[0] / 100.0  # Start angle in degrees
            
            # Extract point data (12 points per packet)
            points = []
            for i in range(12):
                offset = 7 + i * 3
                if offset + 2 < len(packet):
                    distance = struct.unpack('<H', packet[offset:offset+2])[0]  # Distance in mm
                    intensity = packet[offset+2]  # Intensity
                    
                    # Convert to meters
                    distance_m = distance / 1000.0
                    
                    # Calculate angle for this point
                    angle_deg = start_angle + i * 0.75  # 0.75 degrees per point
                    angle_rad = math.radians(angle_deg)
                    
                    if angle_rad < 0:
                        angle_rad += 2 * math.pi
                    elif angle_rad >= 2 * math.pi:
                        angle_rad -= 2 * math.pi
                    
                    points.append({
                        'angle': angle_rad,
                        'distance': distance_m,
                        'intensity': intensity
                    })
            
            return points
        
        return None
    
    def process_scan_data(self, points):
        """Process scan points and publish LaserScan message"""
        current_time = rospy.Time.now()
        
        # Add points to scan data buffer
        for point in points:
            if self.range_min <= point['distance'] <= self.range_max:
                angle_index = int(point['angle'] * 180 / math.pi)
                self.scan_data[angle_index] = point
        
        # Check if we have a complete scan (time-based or angle-based)
        time_diff = (current_time - self.last_scan_time).to_sec()
        if time_diff > 0.1 or len(self.scan_data) > 300:  # Publish at 10Hz or when enough data
            self.publish_scan(current_time)
            self.scan_data = {}
            self.last_scan_time = current_time
    
    def publish_scan(self, scan_time):
        """Publish LaserScan message"""
        if not self.scan_data:
            return
        
        scan_msg = LaserScan()
        scan_msg.header = Header()
        scan_msg.header.stamp = scan_time
        scan_msg.header.frame_id = self.frame_id
        
        # Scan parameters
        scan_msg.angle_min = self.angle_min
        scan_msg.angle_max = self.angle_max
        scan_msg.angle_increment = math.radians(1.0)  # 1 degree resolution
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 0.1  # 10Hz scan rate
        scan_msg.range_min = self.range_min
        scan_msg.range_max = self.range_max
        
        # Initialize arrays
        num_points = int((scan_msg.angle_max - scan_msg.angle_min) / scan_msg.angle_increment) + 1
        ranges = [float('inf')] * num_points
        intensities = [0.0] * num_points
        
        # Fill in scan data
        for angle_deg, point in self.scan_data.items():
            if 0 <= angle_deg <= 359:
                index = angle_deg
                if self.invert_scan:
                    index = num_points - 1 - index
                
                if 0 <= index < num_points:
                    ranges[index] = point['distance']
                    intensities[index] = float(point['intensity'])
        
        # Set invalid ranges to inf
        for i in range(len(ranges)):
            if ranges[i] == float('inf') or ranges[i] < self.range_min or ranges[i] > self.range_max:
                ranges[i] = float('inf')
        
        scan_msg.ranges = ranges
        scan_msg.intensities = intensities
        
        # Publish scan
        self.scan_pub.publish(scan_msg)
        
        rospy.logdebug("Published scan with {} valid points".format(len([r for r in ranges if r != float('inf')])))
    
    def run(self):
        """Main driver loop"""
        buffer = bytearray()
        
        while not rospy.is_shutdown():
            try:
                # Read data from serial port
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    buffer.extend(data)
                
                # Process complete packets
                while len(buffer) >= 47:
                    # Look for packet start
                    start_idx = -1
                    for i in range(len(buffer) - 1):
                        if buffer[i] == 0x54:
                            start_idx = i
                            break
                    
                    if start_idx == -1:
                        buffer = buffer[-46:]  # Keep last 46 bytes
                        break
                    
                    # Remove data before packet start
                    if start_idx > 0:
                        buffer = buffer[start_idx:]
                    
                    # Check if we have a complete packet
                    if len(buffer) >= 47:
                        packet = buffer[:47]
                        buffer = buffer[47:]
                        
                        # Parse packet
                        points = self.parse_packet(packet)
                        if points:
                            self.process_scan_data(points)
            
            except serial.SerialException as e:
                rospy.logerr("Serial communication error: {}".format(e))
                break
            except Exception as e:
                rospy.logwarn("Error processing Lidar data: {}".format(e))
                continue
        
        # Cleanup
        if hasattr(self, 'serial_port') and self.serial_port.is_open:
            self.serial_port.close()

def main():
    """Main function"""
    try:
        driver = LD19LidarDriver()
        driver.run()
    except rospy.ROSInterruptException:
        rospy.loginfo("LD19 Lidar driver shutting down")
    except Exception as e:
        rospy.logerr("Error in LD19 Lidar driver: {}".format(e))

if __name__ == '__main__':
    main()

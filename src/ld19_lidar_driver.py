#!/usr/bin/env python2
"""LiDAR driver for an LD19-class scanner."""

import math
import rospy
import serial
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Header

from config_utils import load_scout_config
from ld19_protocol import LD19_HEADER
from ld19_protocol import LD19_PACKET_LENGTH
from ld19_protocol import LD19_VER_LEN
from ld19_protocol import LD19ScanAssembler
from ld19_protocol import parse_ld19_packet
from scout_runtime_config import load_site_config
from scout_runtime_config import scout_runtime_device
from scout_runtime_config import scout_runtime_topic


class LD19LidarDriver:
    """Driver for the youyeetoo FHL-LD19 Lidar sensor."""

    def __init__(self):
        rospy.init_node("ld19_lidar_driver", anonymous=False)

        config_path = rospy.get_param("~config_file", None)
        site_path = rospy.get_param("~site_file", None)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        if not isinstance(self.config, dict):
            self.config = {}

        lidar_config = self.config.get("lidar", {})

        self.port = rospy.get_param(
            "~port",
            scout_runtime_device(self.site_config, self.config, "lidar", lidar_config.get("port", "/dev/ttyS4")),
        )
        self.baudrate = rospy.get_param("~baudrate", lidar_config.get("baudrate", 230400))
        self.frame_id = rospy.get_param("~frame_id", lidar_config.get("frame_id", "base_laser"))
        self.angle_min = rospy.get_param("~angle_min", lidar_config.get("angle_min", 0.0))
        self.angle_max = rospy.get_param("~angle_max", lidar_config.get("angle_max", 2 * math.pi))
        self.range_min = rospy.get_param("~range_min", lidar_config.get("range_min", 0.02))
        self.range_max = rospy.get_param("~range_max", lidar_config.get("range_max", 12.0))
        self.invert_scan = rospy.get_param("~invert_scan", lidar_config.get("invert_scan", False))
        self.scan_topic = rospy.get_param(
            "~scan_topic",
            scout_runtime_topic(self.site_config, self.config, "lidar_scan", "/scan"),
        )

        self.scan_pub = rospy.Publisher(self.scan_topic, LaserScan, queue_size=1)
        self.scan_assembler = LD19ScanAssembler(
            angle_min=self.angle_min,
            angle_max=self.angle_max,
            range_min=self.range_min,
            range_max=self.range_max,
            invert_scan=self.invert_scan,
        )
        self.last_scan_stamp = None
        self.accepted_packets = 0
        self.rejected_packets = 0
        self.last_reject_report = None

        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
            rospy.loginfo("Connected to LD19 Lidar on {} at {} baud".format(self.port, self.baudrate))
        except Exception as e:
            rospy.logerr("Failed to connect to Lidar: {}".format(e))
            raise SystemExit(1)

        rospy.loginfo(
            "LD19 lidar driver initialized (config: {}, topic: {})".format(
                self.config_path or "defaults",
                self.scan_topic,
            )
        )

    def publish_scan(self, scan_payload, scan_time):
        """Publish a completed scan revolution."""
        scan_msg = LaserScan()
        scan_msg.header = Header()
        scan_msg.header.stamp = scan_time
        scan_msg.header.frame_id = self.frame_id

        scan_msg.angle_min = self.angle_min
        # angle_max must describe the bearing of the LAST range, not one
        # increment past it, or consumers that derive the beam count from
        # (angle_max - angle_min) / angle_increment expect one range too many.
        scan_msg.angle_increment = scan_payload["angle_increment"]
        beam_count = len(scan_payload["ranges"])
        if beam_count > 1:
            scan_msg.angle_max = self.angle_min + (beam_count - 1) * scan_msg.angle_increment
        else:
            scan_msg.angle_max = self.angle_min
        scan_msg.time_increment = 0.0
        if self.last_scan_stamp is not None:
            scan_msg.scan_time = max(0.0, (scan_time - self.last_scan_stamp).to_sec())
        else:
            scan_msg.scan_time = 0.1
        scan_msg.range_min = self.range_min
        scan_msg.range_max = self.range_max

        scan_msg.ranges = scan_payload["ranges"]
        scan_msg.intensities = scan_payload["intensities"]
        self.scan_pub.publish(scan_msg)

        self.last_scan_stamp = scan_time
        rospy.logdebug("Published scan with {} valid points".format(scan_payload["point_count"]))

    def report_packet_health(self, period_seconds=60.0):
        """Periodically log the CRC reject rate so wiring problems are visible."""
        now = rospy.Time.now()
        if self.last_reject_report is None:
            self.last_reject_report = now
            return
        if (now - self.last_reject_report).to_sec() < period_seconds:
            return

        total = self.accepted_packets + self.rejected_packets
        if total > 0:
            reject_ratio = float(self.rejected_packets) / float(total)
            message = "LD19 packets: {} accepted, {} rejected ({:.2%})".format(
                self.accepted_packets,
                self.rejected_packets,
                reject_ratio,
            )
            # A healthy link rejects almost nothing. A sustained reject rate
            # points at baud, wiring, or connector problems worth fixing before
            # the scan is trusted for mapping.
            if reject_ratio > 0.01:
                rospy.logwarn(message)
            else:
                rospy.loginfo(message)

        self.accepted_packets = 0
        self.rejected_packets = 0
        self.last_reject_report = now

    def run(self):
        """Main driver loop."""
        buffer = bytearray()

        while not rospy.is_shutdown():
            try:
                data = self.serial_port.read(LD19_PACKET_LENGTH)
                if data:
                    buffer.extend(data)

                while len(buffer) >= LD19_PACKET_LENGTH:
                    # Resync on the two-byte header signature rather than the
                    # 0x54 header alone. 0x54 occurs constantly inside distance
                    # and intensity payload, so a header-only scan locks onto
                    # mid-packet garbage regularly; the CRC inside
                    # parse_ld19_packet is what finally rejects it.
                    if buffer[0] != LD19_HEADER or buffer[1] != LD19_VER_LEN:
                        del buffer[0]
                        continue

                    packet = buffer[:LD19_PACKET_LENGTH]
                    parsed = parse_ld19_packet(packet)
                    if parsed is None:
                        self.rejected_packets += 1
                        del buffer[0]
                        continue

                    del buffer[:LD19_PACKET_LENGTH]
                    self.accepted_packets += 1
                    completed_scan = self.scan_assembler.add_packet(parsed)
                    if completed_scan is not None:
                        self.publish_scan(completed_scan, rospy.Time.now())
                    self.report_packet_health()
            except serial.SerialException as e:
                rospy.logerr("Serial communication error: {}".format(e))
                break
            except Exception as e:
                rospy.logwarn("Error processing Lidar data: {}".format(e))
                continue

        if hasattr(self, "serial_port") and self.serial_port.is_open:
            self.serial_port.close()


def main():
    """Main function."""
    try:
        driver = LD19LidarDriver()
        driver.run()
    except rospy.ROSInterruptException:
        rospy.loginfo("LD19 Lidar driver shutting down")
    except Exception as e:
        rospy.logerr("Error in LD19 Lidar driver: {}".format(e))


if __name__ == "__main__":
    main()

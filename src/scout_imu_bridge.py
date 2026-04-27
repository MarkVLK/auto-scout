#!/usr/bin/env python2
"""Normalize the Scout vendor IMU topic."""

from __future__ import print_function

import argparse
import copy

from config_utils import load_scout_config
from scout_runtime_config import load_site_config
from scout_runtime_config import scout_runtime_topic


class ScoutImuBridge(object):
    """Republish the vendor IMU topic with the project frame/topic contract."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import rospy
            from sensor_msgs.msg import Imu
        except ImportError as exc:
            raise SystemExit("Scout IMU bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Imu = Imu
        rospy.init_node("scout_imu_bridge", anonymous=False)
        config_path = rospy.get_param("~config_file", config_path)
        site_path = rospy.get_param("~site_file", site_path)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)

        self.source_topic = rospy.get_param(
            "~source_topic",
            scout_runtime_topic(self.site_config, self.config, "scout_imu", "/SensorNode/imu"),
        )
        self.output_topic = rospy.get_param(
            "~output_topic",
            scout_runtime_topic(self.site_config, self.config, "imu_data", "/scout/imu/data"),
        )
        self.frame_id = rospy.get_param("~frame_id", self.config.get("imu", {}).get("frame_id", "imu_link"))

        self.publisher = rospy.Publisher(self.output_topic, Imu, queue_size=1)
        self.subscriber = rospy.Subscriber(self.source_topic, Imu, self.callback, queue_size=1)

    def callback(self, msg):
        normalized = copy.deepcopy(msg)
        if normalized.header.stamp.to_sec() == 0.0:
            normalized.header.stamp = self.rospy.Time.now()
        normalized.header.frame_id = self.frame_id
        self.publisher.publish(normalized)

    def run(self):
        self.rospy.loginfo(
            "Scout IMU bridge active: %s -> %s (frame_id=%s)",
            self.source_topic,
            self.output_topic,
            self.frame_id,
        )
        self.rospy.spin()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    bridge = ScoutImuBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

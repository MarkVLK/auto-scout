#!/usr/bin/env python2
"""Normalize the Scout vendor IMU topic."""

from __future__ import print_function

import argparse

from scout_runtime_config import scout_runtime_topic
from scout_node_utils import load_runtime_configs
from scout_node_utils import private_param


def _stamp_to_sec(stamp):
    try:
        return stamp.to_sec()
    except AttributeError:
        return float(stamp)


class ScoutImuBridge(object):
    """Republish the vendor IMU topic with the project frame/topic contract."""

    def __init__(
        self,
        config_path=None,
        site_path=None,
        config=None,
        site_config=None,
        init_node=True,
        param_prefix=None,
    ):
        try:
            import rospy
            from sensor_msgs.msg import Imu
        except ImportError as exc:
            raise SystemExit("Scout IMU bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Imu = Imu
        if init_node:
            rospy.init_node("scout_imu_bridge", anonymous=False)
        self.config, self.config_path, self.site_config, self.site_path = load_runtime_configs(
            rospy,
            config_path=config_path,
            site_path=site_path,
            config=config,
            site_config=site_config,
            param_prefix=param_prefix,
        )

        self.source_topic = rospy.get_param(
            private_param(param_prefix, "source_topic"),
            scout_runtime_topic(self.site_config, self.config, "scout_imu", "/SensorNode/imu"),
        )
        self.output_topic = rospy.get_param(
            private_param(param_prefix, "output_topic"),
            scout_runtime_topic(self.site_config, self.config, "imu_data", "/scout/imu/data"),
        )
        self.frame_id = rospy.get_param(
            private_param(param_prefix, "frame_id"),
            self.config.get("imu", {}).get("frame_id", "imu_link"),
        )
        imu_config = self.config.get("imu", {})
        self.max_output_hz = float(
            rospy.get_param(private_param(param_prefix, "max_output_hz"), imu_config.get("output_hz", 50.0))
        )
        self.min_publish_period = 1.0 / self.max_output_hz if self.max_output_hz > 0.0 else 0.0
        self.last_publish_time = None

        self.publisher = rospy.Publisher(self.output_topic, Imu, queue_size=1)
        self.subscriber = rospy.Subscriber(self.source_topic, Imu, self.callback, queue_size=1)

    def should_publish(self, now):
        if self.min_publish_period <= 0.0:
            return True

        now_sec = _stamp_to_sec(now)
        if self.last_publish_time is not None and now_sec - self.last_publish_time < self.min_publish_period:
            return False
        self.last_publish_time = now_sec
        return True

    def normalize_message(self, msg, now):
        normalized = self.Imu()
        normalized.header.stamp = msg.header.stamp
        if _stamp_to_sec(normalized.header.stamp) == 0.0:
            normalized.header.stamp = now
        normalized.header.frame_id = self.frame_id
        normalized.orientation = msg.orientation
        normalized.orientation_covariance = list(msg.orientation_covariance)
        normalized.angular_velocity = msg.angular_velocity
        normalized.angular_velocity_covariance = list(msg.angular_velocity_covariance)
        normalized.linear_acceleration = msg.linear_acceleration
        normalized.linear_acceleration_covariance = list(msg.linear_acceleration_covariance)
        return normalized

    def callback(self, msg):
        now = self.rospy.Time.now()
        if not self.should_publish(now):
            return
        self.publisher.publish(self.normalize_message(msg, now))

    def log_active(self):
        self.rospy.loginfo(
            "Scout IMU bridge active: %s -> %s (frame_id=%s, max_output_hz=%.2f)",
            self.source_topic,
            self.output_topic,
            self.frame_id,
            self.max_output_hz,
        )

    def run(self):
        self.log_active()
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

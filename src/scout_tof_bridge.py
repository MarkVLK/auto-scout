#!/usr/bin/env python2
"""Normalize the Scout vendor ToF range topic."""

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


class ScoutToFBridge(object):
    """Republish the vendor ToF range topic with the project frame/topic contract."""

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
            from sensor_msgs.msg import Range
        except ImportError as exc:
            raise SystemExit("Scout ToF bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Range = Range
        if init_node:
            rospy.init_node("scout_tof_bridge", anonymous=False)
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
            scout_runtime_topic(self.site_config, self.config, "scout_tof", "/SensorNode/tof"),
        )
        self.output_topic = rospy.get_param(
            private_param(param_prefix, "output_topic"),
            scout_runtime_topic(self.site_config, self.config, "tof_range", "/scout/tof"),
        )
        self.frame_id = rospy.get_param(
            private_param(param_prefix, "frame_id"),
            self.config.get("tof", {}).get("frame_id", "tof_link"),
        )

        self.publisher = rospy.Publisher(self.output_topic, Range, queue_size=1)
        self.subscriber = rospy.Subscriber(self.source_topic, Range, self.callback, queue_size=1)

    def normalize_message(self, msg, now):
        normalized = self.Range()
        normalized.header.stamp = msg.header.stamp
        if _stamp_to_sec(normalized.header.stamp) == 0.0:
            normalized.header.stamp = now
        normalized.header.frame_id = self.frame_id
        normalized.radiation_type = msg.radiation_type
        normalized.field_of_view = msg.field_of_view
        normalized.min_range = msg.min_range
        normalized.max_range = msg.max_range
        normalized.range = msg.range
        return normalized

    def callback(self, msg):
        self.publisher.publish(self.normalize_message(msg, self.rospy.Time.now()))

    def log_active(self):
        self.rospy.loginfo(
            "Scout ToF bridge active: %s -> %s (frame_id=%s)",
            self.source_topic,
            self.output_topic,
            self.frame_id,
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
    bridge = ScoutToFBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

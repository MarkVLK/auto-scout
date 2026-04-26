#!/usr/bin/env python2
"""Bridge standard autonomy Twist commands into the Scout vendor motion topic."""

import argparse

from config_utils import load_scout_config
from scout_runtime_config import load_site_config
from scout_runtime_config import role_config
from scout_runtime_config import role_motion_setting
from scout_runtime_config import scout_runtime_topic


class ScoutMotionBridge:
    """Republish standard REP-103 motion commands onto the Scout vendor interface."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import rospy
            from geometry_msgs.msg import Twist
        except ImportError as exc:
            raise SystemExit("Scout motion bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Twist = Twist
        rospy.init_node("scout_motion_bridge", anonymous=False)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        scout = role_config(self.site_config, "scout")

        self.input_topic = rospy.get_param(
            "~input_topic",
            scout_runtime_topic(self.site_config, self.config, "autonomy_cmd_vel", "/scout/cmd_vel_companion"),
        )
        self.output_topic = rospy.get_param(
            "~output_topic",
            scout_runtime_topic(self.site_config, self.config, "vendor_cmd_vel", "/cmd_vel_force"),
        )
        self.forward_axis = rospy.get_param("~forward_axis", role_motion_setting(scout, "forward_axis", "y"))

        self.publisher = rospy.Publisher(self.output_topic, Twist, queue_size=1)
        self.subscriber = rospy.Subscriber(self.input_topic, Twist, self.callback, queue_size=1)

    def callback(self, msg):
        vendor = self.Twist()
        if self.forward_axis == "x":
            vendor.linear.x = msg.linear.x
            vendor.linear.y = msg.linear.y
        else:
            vendor.linear.x = msg.linear.y
            vendor.linear.y = msg.linear.x
        vendor.linear.z = msg.linear.z
        vendor.angular.x = msg.angular.x
        vendor.angular.y = msg.angular.y
        vendor.angular.z = msg.angular.z
        self.publisher.publish(vendor)

    def run(self):
        self.rospy.loginfo(
            "Scout motion bridge active: %s -> %s (forward_axis=%s)",
            self.input_topic,
            self.output_topic,
            self.forward_axis,
        )
        self.rospy.spin()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    bridge = ScoutMotionBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

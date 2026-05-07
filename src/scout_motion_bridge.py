#!/usr/bin/env python2
"""Bridge standard autonomy Twist commands into the Scout vendor motion topic."""

import argparse

from scout_runtime_config import role_config
from scout_runtime_config import role_motion_setting
from scout_runtime_config import scout_runtime_topic
from scout_node_utils import load_runtime_configs
from scout_node_utils import private_param


class ScoutMotionBridge:
    """Republish standard REP-103 motion commands onto the Scout vendor interface."""

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
            from geometry_msgs.msg import Twist
        except ImportError as exc:
            raise SystemExit("Scout motion bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Twist = Twist
        if init_node:
            rospy.init_node("scout_motion_bridge", anonymous=False)
        self.config, self.config_path, self.site_config, self.site_path = load_runtime_configs(
            rospy,
            config_path=config_path,
            site_path=site_path,
            config=config,
            site_config=site_config,
            param_prefix=param_prefix,
        )
        scout = role_config(self.site_config, "scout")

        self.input_topic = rospy.get_param(
            private_param(param_prefix, "input_topic"),
            scout_runtime_topic(self.site_config, self.config, "autonomy_cmd_vel", "/scout/cmd_vel_companion"),
        )
        self.output_topic = rospy.get_param(
            private_param(param_prefix, "output_topic"),
            scout_runtime_topic(self.site_config, self.config, "vendor_cmd_vel", "/cmd_vel_force"),
        )
        self.forward_axis = rospy.get_param(
            private_param(param_prefix, "forward_axis"),
            role_motion_setting(scout, "forward_axis", "y"),
        )

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

    def log_active(self):
        self.rospy.loginfo(
            "Scout motion bridge active: %s -> %s (forward_axis=%s)",
            self.input_topic,
            self.output_topic,
            self.forward_axis,
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
    bridge = ScoutMotionBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

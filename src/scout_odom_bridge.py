#!/usr/bin/env python2
"""Bridge vendor odometry into standard /odom plus TF."""

import argparse

from config_utils import load_scout_config
from scout_runtime_config import load_site_config
from scout_runtime_config import role_config
from scout_runtime_config import role_motion_setting
from scout_runtime_config import scout_runtime_topic


class ScoutOdomBridge:
    """Republish Scout vendor odometry on standard ROS interfaces."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import rospy
            from nav_msgs.msg import Odometry
        except ImportError as exc:
            raise SystemExit("Scout odom bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Odometry = Odometry
        self.TransformStamped = None
        self.TFMessage = None
        self.tf_publisher = None
        rospy.init_node("scout_odom_bridge", anonymous=False)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        scout = role_config(self.site_config, "scout")

        self.source_topic = rospy.get_param(
            "~source_topic",
            scout_runtime_topic(self.site_config, self.config, "odom", "/MotorNode/baselink_odom_relative"),
        )
        self.output_topic = rospy.get_param("~output_topic", "/odom")
        self.forward_axis = rospy.get_param("~forward_axis", role_motion_setting(scout, "forward_axis", "y"))
        self.output_frame = rospy.get_param("~frame_id", "odom")
        self.output_child_frame = rospy.get_param("~child_frame_id", "base_link")

        self.publisher = rospy.Publisher(self.output_topic, Odometry, queue_size=10)
        self._setup_tf_publisher()
        self.subscriber = rospy.Subscriber(self.source_topic, Odometry, self.callback, queue_size=10)

    def _setup_tf_publisher(self):
        try:
            from geometry_msgs.msg import TransformStamped
            from tf2_msgs.msg import TFMessage
        except Exception as exc:
            self.rospy.logwarn(
                "Scout odom bridge running without TF publishing; /odom remains active: %s",
                exc,
            )
            return

        try:
            self.TransformStamped = TransformStamped
            self.TFMessage = TFMessage
            self.tf_publisher = self.rospy.Publisher("/tf", TFMessage, queue_size=10)
        except Exception as exc:
            self.TransformStamped = None
            self.TFMessage = None
            self.tf_publisher = None
            self.rospy.logwarn(
                "Scout odom bridge could not create /tf publisher; /odom remains active: %s",
                exc,
            )

    def _normalize_twist(self, twist):
        if self.forward_axis == "x":
            return twist
        body_twist = twist.twist if hasattr(twist, "twist") else twist
        body_twist.linear.x, body_twist.linear.y = body_twist.linear.y, body_twist.linear.x
        return twist

    def tf_available(self):
        return bool(self.tf_publisher and self.TransformStamped and self.TFMessage)

    def callback(self, msg):
        odom = self.Odometry()
        odom.header = msg.header
        odom.header.frame_id = self.output_frame
        odom.child_frame_id = self.output_child_frame
        odom.pose = msg.pose
        odom.twist = self._normalize_twist(msg.twist)
        self.publisher.publish(odom)

        if not self.tf_available():
            return

        transform = self.TransformStamped()
        transform.header.stamp = odom.header.stamp
        transform.header.frame_id = self.output_frame
        transform.child_frame_id = self.output_child_frame
        transform.transform.translation.x = odom.pose.pose.position.x
        transform.transform.translation.y = odom.pose.pose.position.y
        transform.transform.translation.z = odom.pose.pose.position.z
        transform.transform.rotation = odom.pose.pose.orientation
        tf_message = self.TFMessage()
        tf_message.transforms = [transform]
        self.tf_publisher.publish(tf_message)

    def run(self):
        self.rospy.loginfo(
            "Scout odom bridge active: %s -> %s (tf=%s)",
            self.source_topic,
            self.output_topic,
            "enabled" if self.tf_available() else "degraded",
        )
        self.rospy.spin()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    bridge = ScoutOdomBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

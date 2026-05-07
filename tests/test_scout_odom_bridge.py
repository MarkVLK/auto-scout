#!/usr/bin/env python3
"""Unit tests for Scout odometry normalization and TF publishing."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scout_odom_bridge
import scout_node_utils


class FakePublisher:
    def __init__(self, topic):
        self.topic = topic
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeRospy(types.ModuleType):
    def __init__(self):
        super(FakeRospy, self).__init__("rospy")
        self.publishers = {}
        self.subscribers = []
        self.warnings = []

    def init_node(self, *args, **kwargs):
        return None

    def get_param(self, name, default=None):
        return default

    def Publisher(self, topic, msg_type, queue_size=10):
        publisher = FakePublisher(topic)
        self.publishers[topic] = publisher
        return publisher

    def Subscriber(self, topic, msg_type, callback, queue_size=10):
        self.subscribers.append((topic, msg_type, callback, queue_size))
        return object()

    def logwarn(self, message, *args):
        self.warnings.append(message % args if args else message)


class FakeStamp:
    def to_sec(self):
        return 1.0


class FakeHeader:
    def __init__(self):
        self.stamp = FakeStamp()
        self.frame_id = ""


class FakeVector:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class FakeOrientation:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.w = 1.0


class FakePosePose:
    def __init__(self):
        self.position = FakeVector()
        self.orientation = FakeOrientation()


class FakePose:
    def __init__(self):
        self.pose = FakePosePose()


class FakeTwistTwist:
    def __init__(self):
        self.linear = FakeVector()
        self.angular = FakeVector()


class FakeTwist:
    def __init__(self):
        self.twist = FakeTwistTwist()


class FakeOdometry:
    def __init__(self):
        self.header = FakeHeader()
        self.child_frame_id = ""
        self.pose = FakePose()
        self.twist = FakeTwist()


class FakeTransform:
    def __init__(self):
        self.header = FakeHeader()
        self.child_frame_id = ""
        self.transform = types.SimpleNamespace(
            translation=FakeVector(),
            rotation=FakeOrientation(),
        )


class FakeTFMessage:
    def __init__(self, transforms=None):
        self.transforms = transforms or []


def fake_ros_modules(include_tf=True):
    rospy = FakeRospy()

    nav_msgs = types.ModuleType("nav_msgs")
    nav_msgs_msg = types.ModuleType("nav_msgs.msg")
    nav_msgs_msg.Odometry = FakeOdometry
    nav_msgs.msg = nav_msgs_msg

    modules = {
        "rospy": rospy,
        "nav_msgs": nav_msgs,
        "nav_msgs.msg": nav_msgs_msg,
    }

    if include_tf:
        geometry_msgs = types.ModuleType("geometry_msgs")
        geometry_msgs_msg = types.ModuleType("geometry_msgs.msg")
        geometry_msgs_msg.TransformStamped = FakeTransform
        geometry_msgs.msg = geometry_msgs_msg
        tf2_msgs = types.ModuleType("tf2_msgs")
        tf2_msgs_msg = types.ModuleType("tf2_msgs.msg")
        tf2_msgs_msg.TFMessage = FakeTFMessage
        tf2_msgs.msg = tf2_msgs_msg
        modules.update(
            {
                "geometry_msgs": geometry_msgs,
                "geometry_msgs.msg": geometry_msgs_msg,
                "tf2_msgs": tf2_msgs,
                "tf2_msgs.msg": tf2_msgs_msg,
            }
        )

    return rospy, modules


def make_bridge(include_tf=True):
    rospy, modules = fake_ros_modules(include_tf=include_tf)
    patches = [
        patch.dict(sys.modules, modules),
        patch.object(scout_node_utils, "load_scout_config", return_value=({}, None)),
        patch.object(scout_node_utils, "load_site_config", return_value=({}, None)),
        patch.object(scout_odom_bridge, "role_config", return_value={}),
        patch.object(scout_odom_bridge, "role_motion_setting", return_value="y"),
        patch.object(
            scout_odom_bridge,
            "scout_runtime_topic",
            return_value="/MotorNode/baselink_odom_relative",
        ),
    ]
    for item in patches:
        item.start()
    try:
        return scout_odom_bridge.ScoutOdomBridge(), rospy
    finally:
        for item in reversed(patches):
            item.stop()


class ScoutOdomBridgeTest(unittest.TestCase):
    def test_bridge_does_not_import_tf2_ros(self):
        source = (SRC_DIR / "scout_odom_bridge.py").read_text(encoding="utf-8")
        self.assertNotIn("tf2_ros", source)

    def test_normal_path_publishes_odom_and_tf(self):
        bridge, rospy = make_bridge(include_tf=True)
        message = FakeOdometry()
        message.pose.pose.position.x = 1.2
        message.pose.pose.position.y = -0.4
        message.twist.twist.linear.x = 0.1
        message.twist.twist.linear.y = 0.3

        bridge.callback(message)

        odom = rospy.publishers["/odom"].messages[-1]
        self.assertEqual(odom.header.frame_id, "odom")
        self.assertEqual(odom.child_frame_id, "base_link")
        self.assertAlmostEqual(odom.twist.twist.linear.x, 0.3)
        self.assertAlmostEqual(odom.twist.twist.linear.y, 0.1)

        tf_message = rospy.publishers["/tf"].messages[-1]
        transform = tf_message.transforms[0]
        self.assertEqual(transform.header.frame_id, "odom")
        self.assertEqual(transform.child_frame_id, "base_link")
        self.assertAlmostEqual(transform.transform.translation.x, 1.2)
        self.assertAlmostEqual(transform.transform.translation.y, -0.4)

    def test_missing_tf_message_types_keeps_odom_active(self):
        bridge, rospy = make_bridge(include_tf=False)

        bridge.callback(FakeOdometry())

        self.assertIn("/odom", rospy.publishers)
        self.assertNotIn("/tf", rospy.publishers)
        self.assertEqual(len(rospy.publishers["/odom"].messages), 1)
        self.assertFalse(bridge.tf_available())
        self.assertTrue(any("without TF publishing" in warning for warning in rospy.warnings))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for lightweight Scout sensor normalization bridges."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import scout_imu_bridge
import scout_node_utils
import scout_tof_bridge
from scout_imu_bridge import ScoutImuBridge
from scout_tof_bridge import ScoutToFBridge


class FakeStamp:
    def __init__(self, seconds):
        self.seconds = float(seconds)

    def to_sec(self):
        return self.seconds


class FakeHeader:
    def __init__(self, stamp=None, frame_id=""):
        self.stamp = stamp or FakeStamp(0.0)
        self.frame_id = frame_id


class FakePublisher:
    def __init__(self, topic, data_class, queue_size=1):
        self.topic = topic
        self.data_class = data_class
        self.queue_size = queue_size
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeSubscriber:
    def __init__(self, topic, data_class, callback, queue_size=1):
        self.topic = topic
        self.data_class = data_class
        self.callback = callback
        self.queue_size = queue_size


class FakeRospy(types.ModuleType):
    def __init__(self):
        super(FakeRospy, self).__init__("rospy")
        self.params = {}
        self.publishers = []
        self.subscribers = []
        self.now_seconds = 100.0
        self.Time = types.SimpleNamespace(now=lambda: FakeStamp(self.now_seconds))

    def init_node(self, name, anonymous=False):
        self.node_name = name
        self.anonymous = anonymous

    def get_param(self, name, default=None):
        return self.params.get(name, default)

    def Publisher(self, topic, data_class, queue_size=1):
        publisher = FakePublisher(topic, data_class, queue_size=queue_size)
        self.publishers.append(publisher)
        return publisher

    def Subscriber(self, topic, data_class, callback, queue_size=1):
        subscriber = FakeSubscriber(topic, data_class, callback, queue_size=queue_size)
        self.subscribers.append(subscriber)
        return subscriber

    def loginfo(self, *args):
        return None


class FakeImu:
    def __init__(self):
        self.header = FakeHeader()
        self.orientation = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
        self.orientation_covariance = [0.0] * 9
        self.angular_velocity = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.angular_velocity_covariance = [0.0] * 9
        self.linear_acceleration = types.SimpleNamespace(x=0.0, y=0.0, z=9.8)
        self.linear_acceleration_covariance = [0.0] * 9


class FakeRange:
    def __init__(self):
        self.header = FakeHeader()
        self.radiation_type = 1
        self.field_of_view = 0.4
        self.min_range = 0.03
        self.max_range = 2.0
        self.range = 0.5


def sensor_modules():
    sensor_msgs = types.ModuleType("sensor_msgs")
    sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")
    sensor_msgs_msg.Imu = FakeImu
    sensor_msgs_msg.Range = FakeRange
    sensor_msgs.msg = sensor_msgs_msg
    return sensor_msgs, sensor_msgs_msg


class ScoutSensorBridgeTest(unittest.TestCase):
    def make_imu_bridge(self, config=None, params=None):
        fake_rospy = FakeRospy()
        fake_rospy.params.update(params or {})
        sensor_msgs, sensor_msgs_msg = sensor_modules()
        site_config = {
            "roles": {
                "scout": {
                    "topics": {
                        "scout_imu": "/SensorNode/imu",
                        "imu_data": "/scout/imu/data",
                    },
                },
            },
        }
        with patch.dict(sys.modules, {"rospy": fake_rospy, "sensor_msgs": sensor_msgs, "sensor_msgs.msg": sensor_msgs_msg}):
            with patch.object(
                scout_node_utils,
                "load_scout_config",
                return_value=(config or {"imu": {"frame_id": "imu_link", "output_hz": 50.0}}, "config.yaml"),
            ):
                with patch.object(scout_node_utils, "load_site_config", return_value=(site_config, "site.yaml")):
                    bridge = ScoutImuBridge(config_path="config.yaml", site_path="site.yaml")
        return bridge, fake_rospy

    def make_tof_bridge(self):
        fake_rospy = FakeRospy()
        sensor_msgs, sensor_msgs_msg = sensor_modules()
        site_config = {
            "roles": {
                "scout": {
                    "topics": {
                        "scout_tof": "/SensorNode/tof",
                        "tof_range": "/scout/tof",
                    },
                },
            },
        }
        with patch.dict(sys.modules, {"rospy": fake_rospy, "sensor_msgs": sensor_msgs, "sensor_msgs.msg": sensor_msgs_msg}):
            with patch.object(
                scout_node_utils,
                "load_scout_config",
                return_value=({"tof": {"frame_id": "tof_link"}}, "config.yaml"),
            ):
                with patch.object(scout_node_utils, "load_site_config", return_value=(site_config, "site.yaml")):
                    bridge = ScoutToFBridge(config_path="config.yaml", site_path="site.yaml")
        return bridge, fake_rospy

    def test_imu_bridge_throttles_high_rate_source(self):
        bridge, fake_rospy = self.make_imu_bridge()
        msg = FakeImu()

        fake_rospy.now_seconds = 100.000
        bridge.callback(msg)
        fake_rospy.now_seconds = 100.005
        bridge.callback(msg)
        fake_rospy.now_seconds = 100.025
        bridge.callback(msg)

        self.assertEqual(len(bridge.publisher.messages), 2)
        self.assertEqual(bridge.max_output_hz, 50.0)

    def test_imu_bridge_preserves_payload_and_sets_frame_without_deepcopy(self):
        bridge, fake_rospy = self.make_imu_bridge(params={"~max_output_hz": 0.0})
        msg = FakeImu()
        msg.header.stamp = FakeStamp(12.5)
        msg.header.frame_id = "vendor_imu"
        msg.orientation.x = 1.0
        msg.angular_velocity.z = 2.0
        msg.linear_acceleration.y = 3.0
        msg.orientation_covariance = list(range(9))

        bridge.callback(msg)

        output = bridge.publisher.messages[0]
        self.assertIsNot(output, msg)
        self.assertEqual(output.header.stamp.to_sec(), 12.5)
        self.assertEqual(output.header.frame_id, "imu_link")
        self.assertEqual(output.orientation.x, 1.0)
        self.assertEqual(output.angular_velocity.z, 2.0)
        self.assertEqual(output.linear_acceleration.y, 3.0)
        self.assertEqual(output.orientation_covariance, list(range(9)))

    def test_tof_bridge_preserves_range_payload_and_sets_frame_without_deepcopy(self):
        bridge, fake_rospy = self.make_tof_bridge()
        msg = FakeRange()
        msg.header.stamp = FakeStamp(0.0)
        msg.header.frame_id = "vendor_tof"
        msg.radiation_type = 7
        msg.field_of_view = 0.55
        msg.min_range = 0.04
        msg.max_range = 3.0
        msg.range = 0.42
        fake_rospy.now_seconds = 101.0

        bridge.callback(msg)

        output = bridge.publisher.messages[0]
        self.assertIsNot(output, msg)
        self.assertEqual(output.header.stamp.to_sec(), 101.0)
        self.assertEqual(output.header.frame_id, "tof_link")
        self.assertEqual(output.radiation_type, 7)
        self.assertEqual(output.field_of_view, 0.55)
        self.assertEqual(output.min_range, 0.04)
        self.assertEqual(output.max_range, 3.0)
        self.assertEqual(output.range, 0.42)

    def test_core_runtime_uses_single_init_node_and_component_namespaces(self):
        core_source = (SRC_DIR / "scout_core_runtime.py").read_text(encoding="utf-8")
        launch_source = (REPO_ROOT / "launch" / "scout_runtime.launch").read_text(encoding="utf-8")

        self.assertEqual(core_source.count("rospy.init_node("), 1)
        for namespace in ['"~tof"', '"~imu"', '"~odom"', '"~battery"', '"~safety"', '"~motion"']:
            self.assertIn("param_prefix={}".format(namespace), core_source)
        self.assertIn('name="scout_core_runtime"', launch_source)
        self.assertIn('unless="$(arg use_core_runtime)"', launch_source)


if __name__ == "__main__":
    unittest.main()

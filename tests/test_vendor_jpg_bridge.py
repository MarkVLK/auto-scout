#!/usr/bin/env python3
"""Unit tests for the vendor JPG bridge."""

import builtins
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import vendor_jpg_bridge
from vendor_jpg_bridge import VIDEO_STREAM_H264
from vendor_jpg_bridge import VIDEO_STREAM_JPG
from vendor_jpg_bridge import VendorJpgBridge
from vendor_jpg_bridge import parse_vendor_frame


def serialized_frame(frame_type=VIDEO_STREAM_JPG, data=b"\xff\xd8\xff\xe0"):
    return struct.pack(
        "<IQIbIiiiiI",
        7,
        123456789,
        3,
        frame_type,
        8,
        640,
        480,
        0,
        0,
        len(data),
    ) + data


class FakeAnyMsg:
    def __init__(self, payload):
        self._buff = payload


class FakePublisher:
    def __init__(self, topic, data_class, queue_size=1):
        self.topic = topic
        self.data_class = data_class
        self.queue_size = queue_size
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeRospy:
    class AnyMsg:
        pass

    class Time:
        @staticmethod
        def now():
            return "receive-time"

    def __init__(self):
        self.publishers = []
        self.subscribers = []

    def init_node(self, name, anonymous=False):
        self.node_name = name
        self.anonymous = anonymous

    def get_param(self, name, default=None):
        return default

    def Publisher(self, topic, data_class, queue_size=1):
        publisher = FakePublisher(topic, data_class, queue_size=queue_size)
        self.publishers.append(publisher)
        return publisher

    def Subscriber(self, topic, data_class, callback, queue_size=1):
        subscriber = {
            "topic": topic,
            "data_class": data_class,
            "callback": callback,
            "queue_size": queue_size,
        }
        self.subscribers.append(subscriber)
        return subscriber

    def loginfo(self, *args):
        return None

    def spin(self):
        return None


class FakeCompressedImage:
    def __init__(self):
        self.header = types.SimpleNamespace(stamp=None, frame_id="")
        self.format = ""
        self.data = b""


class VendorFrameParserTest(unittest.TestCase):
    def test_valid_jpg_frame_extracts_payload(self):
        payload = b"\xff\xd8payload\xff\xd9"
        frame = parse_vendor_frame(FakeAnyMsg(serialized_frame(VIDEO_STREAM_JPG, payload)))

        self.assertEqual(frame["seq"], 7)
        self.assertEqual(frame["stamp"], 123456789)
        self.assertEqual(frame["session"], 3)
        self.assertEqual(frame["type"], VIDEO_STREAM_JPG)
        self.assertEqual(frame["data"], payload)

    def test_h264_frame_is_parseable_but_not_jpg(self):
        frame = parse_vendor_frame(FakeAnyMsg(serialized_frame(VIDEO_STREAM_H264, b"h264")))

        self.assertEqual(frame["type"], VIDEO_STREAM_H264)
        self.assertEqual(frame["data"], b"h264")

    def test_truncated_frame_is_ignored(self):
        self.assertIsNone(parse_vendor_frame(FakeAnyMsg(serialized_frame()[:-2])))
        self.assertIsNone(parse_vendor_frame(FakeAnyMsg(b"\x00\x01")))


class VendorJpgBridgeTest(unittest.TestCase):
    def make_bridge(self):
        fake_rospy = FakeRospy()
        sensor_msgs = types.ModuleType("sensor_msgs")
        sensor_msgs_msg = types.ModuleType("sensor_msgs.msg")
        sensor_msgs_msg.CompressedImage = FakeCompressedImage
        sensor_msgs.msg = sensor_msgs_msg
        site_config = {
            "roles": {
                "scout": {
                    "topics": {
                        "vendor_camera_jpg": "/CoreNode/jpg",
                        "camera_compressed": "/camera/image_raw/compressed",
                    },
                },
            },
        }

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "cv2" or name.startswith("cv2."):
                raise AssertionError("vendor_jpg_bridge must not import OpenCV")
            return real_import(name, *args, **kwargs)

        with patch.dict(
            sys.modules,
            {
                "rospy": fake_rospy,
                "sensor_msgs": sensor_msgs,
                "sensor_msgs.msg": sensor_msgs_msg,
            },
        ):
            with patch.object(vendor_jpg_bridge, "load_scout_config", return_value=({"camera": {"frame_id": "camera_link"}}, "config.yaml")):
                with patch.object(vendor_jpg_bridge, "load_site_config", return_value=(site_config, "site.yaml")):
                    with patch("builtins.__import__", side_effect=guarded_import):
                        bridge = VendorJpgBridge(config_path="config.yaml", site_path="site.yaml")
        return bridge, fake_rospy

    def test_bridge_publishes_valid_jpg_as_compressed_image(self):
        bridge, fake_rospy = self.make_bridge()

        bridge.callback(FakeAnyMsg(serialized_frame(VIDEO_STREAM_JPG, b"\xff\xd8jpg")))

        self.assertEqual(bridge.source_topic, "/CoreNode/jpg")
        self.assertEqual(bridge.output_topic, "/camera/image_raw/compressed")
        self.assertEqual(fake_rospy.subscribers[0]["topic"], "/CoreNode/jpg")
        self.assertIs(fake_rospy.subscribers[0]["data_class"], FakeRospy.AnyMsg)
        self.assertEqual(len(bridge.publisher.messages), 1)
        image = bridge.publisher.messages[0]
        self.assertEqual(image.header.stamp, "receive-time")
        self.assertEqual(image.header.frame_id, "camera_link")
        self.assertEqual(image.format, "jpeg")
        self.assertEqual(image.data, b"\xff\xd8jpg")

    def test_bridge_ignores_h264_and_malformed_frames(self):
        bridge, _ = self.make_bridge()

        bridge.callback(FakeAnyMsg(serialized_frame(VIDEO_STREAM_H264, b"h264")))
        bridge.callback(FakeAnyMsg(b"\x00\x01"))

        self.assertEqual(bridge.publisher.messages, [])


if __name__ == "__main__":
    unittest.main()

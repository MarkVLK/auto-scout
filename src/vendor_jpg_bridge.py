#!/usr/bin/env python2
"""Bridge Moorebot vendor JPG frames into standard compressed images."""

from __future__ import print_function

import argparse
import struct
import time

from config_utils import load_scout_config
from scout_runtime_config import load_site_config
from scout_runtime_config import scout_runtime_topic


VIDEO_STREAM_H264 = 0
VIDEO_STREAM_JPG = 1
AUDIO_STREAM_AAC = 2
_FRAME_PREFIX_FORMAT = "<IQIbIiiiiI"
_FRAME_PREFIX_SIZE = struct.calcsize(_FRAME_PREFIX_FORMAT)


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ["1", "true", "yes", "on"]


def _serialized_bytes(message):
    raw = getattr(message, "_buff", message)
    if hasattr(raw, "getvalue"):
        raw = raw.getvalue()
    if raw is None:
        return b""
    if isinstance(raw, bytearray):
        return bytes(raw)
    if hasattr(raw, "tobytes"):
        return raw.tobytes()
    try:
        text_type = unicode
    except NameError:
        text_type = str
    if isinstance(raw, text_type):
        return raw.encode("latin1")
    return raw


def parse_vendor_frame(message):
    """Parse a serialized roller_eye/frame AnyMsg payload."""
    raw = _serialized_bytes(message)
    if len(raw) < _FRAME_PREFIX_SIZE:
        return None
    try:
        seq, stamp, session, frame_type, oseq, par1, par2, par3, par4, data_len = struct.unpack_from(
            _FRAME_PREFIX_FORMAT,
            raw,
            0,
        )
    except struct.error:
        return None

    data_start = _FRAME_PREFIX_SIZE
    data_end = data_start + data_len
    if data_len < 0 or len(raw) < data_end:
        return None
    return {
        "seq": seq,
        "stamp": stamp,
        "session": session,
        "type": frame_type,
        "oseq": oseq,
        "par1": par1,
        "par2": par2,
        "par3": par3,
        "par4": par4,
        "data": raw[data_start:data_end],
    }


class VendorJpgBridge(object):
    """Publish vendor JPG frame payloads as sensor_msgs/CompressedImage."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import rospy
            from sensor_msgs.msg import CompressedImage
        except ImportError as exc:
            raise SystemExit("Vendor JPG bridge requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.CompressedImage = CompressedImage
        rospy.init_node("vendor_jpg_bridge", anonymous=False)

        config_path = rospy.get_param("~config_file", config_path)
        site_path = rospy.get_param("~site_file", site_path)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        camera_config = self.config.get("camera", {}) if isinstance(self.config.get("camera", {}), dict) else {}

        self.source_topic = rospy.get_param(
            "~source_topic",
            scout_runtime_topic(self.site_config, self.config, "vendor_camera_jpg", "/CoreNode/jpg"),
        )
        self.output_topic = rospy.get_param(
            "~output_topic",
            scout_runtime_topic(self.site_config, self.config, "camera_compressed", "/camera/image_raw/compressed"),
        )
        self.frame_id = rospy.get_param("~frame_id", camera_config.get("frame_id", "camera_link"))
        self.lazy = _as_bool(rospy.get_param("~lazy", camera_config.get("lazy_vendor_jpg_bridge", True)), True)
        self.idle_timeout = float(
            rospy.get_param("~idle_timeout", camera_config.get("vendor_jpg_idle_timeout", 5.0))
        )
        self.poll_hz = float(rospy.get_param("~poll_hz", camera_config.get("vendor_jpg_poll_hz", 2.0)))

        self.publisher = rospy.Publisher(self.output_topic, CompressedImage, queue_size=1)
        self.subscriber = None
        self.last_consumer_time = None
        if not self.lazy:
            self.ensure_subscribed()

    def _now_seconds(self):
        try:
            now = self.rospy.Time.now()
            if hasattr(now, "to_sec"):
                return now.to_sec()
        except Exception:
            pass
        return time.time()

    def output_has_consumers(self):
        if not hasattr(self.publisher, "get_num_connections"):
            return True
        return self.publisher.get_num_connections() > 0

    def ensure_subscribed(self):
        if self.subscriber is not None:
            return
        self.subscriber = self.rospy.Subscriber(self.source_topic, self.rospy.AnyMsg, self.callback, queue_size=1)
        self.rospy.loginfo("Vendor JPG bridge subscribed to %s", self.source_topic)

    def stop_subscription(self):
        if self.subscriber is None:
            return
        unregister = getattr(self.subscriber, "unregister", None)
        if unregister:
            unregister()
        self.subscriber = None
        self.rospy.loginfo("Vendor JPG bridge idled; unsubscribed from %s", self.source_topic)

    def update_subscription(self):
        if not self.lazy:
            self.ensure_subscribed()
            return

        now = self._now_seconds()
        if self.output_has_consumers():
            self.last_consumer_time = now
            self.ensure_subscribed()
            return

        if self.subscriber is None:
            return
        if self.last_consumer_time is None or now - self.last_consumer_time >= self.idle_timeout:
            self.stop_subscription()

    def callback(self, msg):
        if self.lazy and not self.output_has_consumers():
            return

        frame = parse_vendor_frame(msg)
        if not frame or frame.get("type") != VIDEO_STREAM_JPG:
            return

        image = self.CompressedImage()
        image.header.stamp = self.rospy.Time.now()
        image.header.frame_id = self.frame_id
        image.format = "jpeg"
        image.data = frame["data"]
        self.publisher.publish(image)

    def run(self):
        self.rospy.loginfo(
            "Vendor JPG bridge active: %s -> %s (lazy=%s, idle_timeout=%.1fs)",
            self.source_topic,
            self.output_topic,
            self.lazy,
            self.idle_timeout,
        )
        if not self.lazy:
            self.rospy.spin()
            return

        rate = self.rospy.Rate(self.poll_hz)
        while not self.rospy.is_shutdown():
            self.update_subscription()
            rate.sleep()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    bridge = VendorJpgBridge(config_path=args.config, site_path=args.site)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Lightweight camera bridge for the clean-slate Scout runtime."""

import argparse

from config_utils import load_scout_config


class ScoutCameraDriver:
    """Publish compressed camera frames without onboard visual odometry."""

    def __init__(self, config_path=None):
        try:
            import cv2
            import rospy
            from sensor_msgs.msg import CompressedImage
        except ImportError as exc:
            raise SystemExit("Camera bridge requires ROS + OpenCV packages: {}".format(exc))

        self.cv2 = cv2
        self.rospy = rospy
        self.CompressedImage = CompressedImage
        config_path = rospy.get_param("~config_file", config_path)
        self.config, self.config_path = load_scout_config(config_path)

        camera_config = self.config.get("camera", {})
        topic_config = self.config.get("topics", {})

        raw_device = rospy.get_param("~device", camera_config.get("device", "/dev/video0"))
        self.device = int(raw_device) if isinstance(raw_device, str) and raw_device.isdigit() else raw_device
        self.width = rospy.get_param("~width", camera_config.get("width", 640))
        self.height = rospy.get_param("~height", camera_config.get("height", 480))
        self.fps = rospy.get_param("~fps", camera_config.get("fps", 15))
        self.frame_id = rospy.get_param("~frame_id", camera_config.get("frame_id", "camera_link"))
        self.topic = rospy.get_param(
            "~topic",
            topic_config.get("camera_compressed", "/camera/image_raw/compressed"),
        )

        rospy.init_node("scout_camera_driver", anonymous=False)
        self.publisher = rospy.Publisher(self.topic, CompressedImage, queue_size=1)

        self.capture = cv2.VideoCapture(self.device)
        if not self.capture.isOpened():
            raise SystemExit("Cannot open camera {}".format(self.device))

        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.capture.set(cv2.CAP_PROP_FPS, self.fps)

    def run(self):
        rate = self.rospy.Rate(self.fps)
        while not self.rospy.is_shutdown():
            ok, frame = self.capture.read()
            if not ok:
                self.rospy.logwarn("Failed to read camera frame")
                rate.sleep()
                continue

            success, encoded = self.cv2.imencode(".jpg", frame)
            if not success:
                self.rospy.logwarn("Failed to encode camera frame")
                rate.sleep()
                continue

            message = self.CompressedImage()
            message.header.stamp = self.rospy.Time.now()
            message.header.frame_id = self.frame_id
            message.format = "jpeg"
            message.data = encoded.tobytes()
            self.publisher.publish(message)
            rate.sleep()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    driver = ScoutCameraDriver(config_path=args.config)
    driver.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

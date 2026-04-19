#!/usr/bin/env python2
"""Companion-side smoke-loop mission runner."""

from __future__ import print_function

import argparse
import json
import os

import requests

from companion_runtime_support import ensure_directory
from companion_runtime_support import load_mission_config
from companion_runtime_support import load_site_config
from companion_runtime_support import role_config
from companion_runtime_support import scout_runtime_topic
from companion_runtime_support import system_capabilities
from companion_runtime_support import utc_timestamp
from config_utils import load_scout_config


class MissionRunError(RuntimeError):
    """Raised when the smoke mission cannot complete safely."""


class CompanionMissionController(object):
    """Execute the smoke-loop mission through the companion ROS stack."""

    def __init__(self, config_path=None, site_path=None, mission_path="smoke_loop", artifact_dir=None):
        try:
            import actionlib
            import rospy
            from actionlib_msgs.msg import GoalStatus
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import CompressedImage
            from std_msgs.msg import String
        except ImportError as exc:
            raise MissionRunError("ROS mission controller requires ROS Python packages: {}".format(exc))

        self.actionlib = actionlib
        self.rospy = rospy
        self.GoalStatus = GoalStatus
        self.MoveBaseAction = MoveBaseAction
        self.MoveBaseGoal = MoveBaseGoal
        self.String = String

        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        self.mission, self.mission_path = load_mission_config(mission_path)

        default_artifact_dir = os.path.join(os.getcwd(), "artifacts", "runs", "remote-smoke-loop")
        self.artifact_dir = artifact_dir or default_artifact_dir
        ensure_directory(self.artifact_dir)
        self.log_path = os.path.join(self.artifact_dir, "mission.log")

        self.latest_image = None
        self.latest_pose = None
        self.pose_seen = False

        rospy.init_node("scout_navigation_controller", anonymous=False)
        self.status_pub = rospy.Publisher("/scout/mission_status", String, queue_size=1)
        self.dock_pub = rospy.Publisher("/scout/runtime/request", String, queue_size=1)
        rospy.Subscriber(
            scout_runtime_topic(self.site_config, self.config, "camera_compressed", "/camera/image_raw/compressed"),
            CompressedImage,
            self.camera_callback,
            queue_size=1,
        )
        rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, self.pose_callback, queue_size=1)
        rospy.Subscriber("/odom", Odometry, self.odom_callback, queue_size=1)
        self.move_base_client = actionlib.SimpleActionClient("move_base", MoveBaseAction)

    def log(self, message):
        line = "[{}] {}".format(utc_timestamp(), message)
        with open(self.log_path, "a") as handle:
            handle.write(line + "\n")
        self.rospy.loginfo(message)
        self.status_pub.publish(line)

    def write_json(self, name, payload):
        target = os.path.join(self.artifact_dir, name)
        with open(target, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def camera_callback(self, msg):
        self.latest_image = msg

    def pose_callback(self, msg):
        self.latest_pose = {
            "source": "amcl_pose",
            "stamp": msg.header.stamp.to_sec(),
            "frame_id": msg.header.frame_id,
        }
        self.pose_seen = True

    def odom_callback(self, msg):
        if self.pose_seen:
            return
        self.latest_pose = {
            "source": "odom",
            "stamp": msg.header.stamp.to_sec(),
            "frame_id": msg.header.frame_id,
        }
        self.pose_seen = True

    def wait_for_pose(self, timeout_seconds=15.0):
        start = self.rospy.Time.now()
        while not self.rospy.is_shutdown():
            if self.pose_seen:
                return
            if (self.rospy.Time.now() - start).to_sec() >= timeout_seconds:
                raise MissionRunError("No pose source became available within {:.1f} seconds".format(timeout_seconds))
            self.rospy.sleep(0.25)

    def wait_for_move_base(self, timeout_seconds=30.0):
        self.log("Waiting for move_base")
        if not self.move_base_client.wait_for_server(self.rospy.Duration(timeout_seconds)):
            raise MissionRunError("move_base action server did not become available")

    def navigate_to_waypoint(self, waypoint_name):
        waypoints = self.config.get("waypoints", {})
        if waypoint_name not in waypoints:
            raise MissionRunError("Waypoint '{}' is not defined".format(waypoint_name))

        waypoint = waypoints[waypoint_name]
        goal = self.MoveBaseGoal()
        goal.target_pose.header.frame_id = self.mission.get("route", {}).get("map_frame", "map")
        goal.target_pose.header.stamp = self.rospy.Time.now()
        goal.target_pose.pose.position.x = waypoint["x"]
        goal.target_pose.pose.position.y = waypoint["y"]
        goal.target_pose.pose.orientation.z = waypoint["z"]
        goal.target_pose.pose.orientation.w = waypoint["w"]

        self.log("Navigating to {}".format(waypoint_name))
        self.move_base_client.send_goal(goal)
        if not self.move_base_client.wait_for_result(self.rospy.Duration(180.0)):
            self.move_base_client.cancel_goal()
            raise MissionRunError("Timed out while navigating to {}".format(waypoint_name))

        state = self.move_base_client.get_state()
        if state != self.GoalStatus.SUCCEEDED:
            raise MissionRunError("Navigation to {} failed with state {}".format(waypoint_name, state))

    def capture_photo(self):
        if self.latest_image is None:
            raise MissionRunError("No compressed camera frame is available for smoke-loop proof capture")

        media_dir = self.site_config["roles"]["companion"]["storage"]["media_dir"]
        output_name = self.mission.get("capture", {}).get("output_name", "smoke-loop-proof.jpg")
        photo_path = os.path.join(media_dir, "{}-{}".format(self._timestamp_for_filename(), output_name))
        ensure_directory(media_dir)

        with open(photo_path, "wb") as handle:
            handle.write(self.latest_image.data)

        self.log("Captured proof photo at {}".format(photo_path))
        return photo_path

    def request_return(self):
        capabilities = system_capabilities(self.site_config)
        return_config = self.mission.get("return", {})

        if capabilities.get("dock", False):
            self.log("Requesting vendor dock behavior")
            self.dock_pub.publish("dock")
            return {"mode": "vendor_dock_requested"}

        fallback_waypoint = return_config.get("fallback_waypoint")
        if not fallback_waypoint:
            raise MissionRunError("Docking is unavailable and no fallback waypoint was configured")

        self.navigate_to_waypoint(fallback_waypoint)
        return {"mode": "fallback_waypoint", "waypoint": fallback_waypoint}

    def send_notification(self, photo_path, return_result):
        notification = self.mission.get("notification", {})
        if not notification.get("enabled", False):
            return {"sent": False, "reason": "disabled"}

        webhook_url = (
            self.site_config["roles"]["companion"].get("notifications", {}).get("webhook_url")
            or self.config.get("storage", {}).get("webhook_url", "")
        )
        if not webhook_url:
            raise MissionRunError("Notification is enabled but no webhook URL is configured")

        payload = {
            "mission": self.mission.get("name", "smoke_loop"),
            "result": "pass",
            "artifact_dir": self.artifact_dir,
            "photo_path": photo_path,
            "return": return_result,
            "timestamp": utc_timestamp(),
        }
        response = requests.post(webhook_url, json=payload, timeout=15)
        response.raise_for_status()
        self.log("Sent webhook notification to {}".format(webhook_url))
        return {"sent": True, "status_code": response.status_code}

    def run_smoke_loop(self):
        self.log("Starting smoke-loop mission")
        self.wait_for_pose()
        self.wait_for_move_base()

        route = self.mission.get("route", {}).get("loop_waypoints", [])
        if not route:
            raise MissionRunError("Mission route does not contain loop_waypoints")

        for waypoint in route:
            self.navigate_to_waypoint(waypoint)

        return_result = self.request_return()
        photo_path = self.capture_photo()
        notification_result = self.send_notification(photo_path, return_result)

        result = {
            "ok": True,
            "mission": self.mission.get("name", "smoke_loop"),
            "route": route,
            "return": return_result,
            "photo_path": photo_path,
            "notification": notification_result,
            "pose": self.latest_pose,
            "artifact_dir": self.artifact_dir,
        }
        self.write_json("mission-result.json", result)
        self.log("Smoke-loop mission completed")
        return result

    def _timestamp_for_filename(self):
        return utc_timestamp().replace("-", "").replace(":", "").split(".")[0]


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--mission", default="smoke_loop")
    parser.add_argument("--artifact-dir", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    controller = CompanionMissionController(
        config_path=args.config,
        site_path=args.site,
        mission_path=args.mission,
        artifact_dir=args.artifact_dir,
    )
    result = controller.run_smoke_loop()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

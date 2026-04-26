"""Lean companion-side smoke mission controller."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from auto_scout.mission_config import load_mission_config
from auto_scout.site_config import load_site_config, scout_runtime_topic, system_capabilities
from config_utils import load_scout_config


class MissionRunError(RuntimeError):
    """Raised when the smoke mission cannot complete safely."""


class CompanionMissionController:
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

        self.artifact_dir = Path(artifact_dir) if artifact_dir else Path.cwd() / "artifacts" / "runs" / "remote-smoke-loop"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.artifact_dir / "mission.log"

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
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        line = "[{}] {}".format(timestamp, message)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.rospy.loginfo(message)
        self.status_pub.publish(line)

    def write_json(self, name, payload):
        target = self.artifact_dir / name
        with target.open("w", encoding="utf-8") as handle:
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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target_dir = Path(media_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        photo_path = target_dir / "{}-{}".format(timestamp, output_name)

        with photo_path.open("wb") as handle:
            handle.write(self.latest_image.data)

        self.log("Captured proof photo at {}".format(photo_path))
        return str(photo_path)

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
            "artifact_dir": str(self.artifact_dir),
            "photo_path": photo_path,
            "return": return_result,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
            "artifact_dir": str(self.artifact_dir),
        }
        self.write_json("mission-result.json", result)
        self.log("Smoke-loop mission completed")
        return result


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--mission", default="smoke_loop")
    parser.add_argument("--artifact-dir", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    controller = CompanionMissionController(
        config_path=args.config,
        site_path=args.site,
        mission_path=args.mission,
        artifact_dir=args.artifact_dir,
    )
    result = controller.run_smoke_loop()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

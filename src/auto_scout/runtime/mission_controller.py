"""Lean companion-side smoke mission controller."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    class _MissingRequests:
        def post(self, *args, **kwargs):
            raise ImportError("requests package is required")

    requests = _MissingRequests()
    REQUESTS_AVAILABLE = False
else:
    REQUESTS_AVAILABLE = True

from auto_scout.mission_config import load_mission_config
from auto_scout.site_config import load_site_config, scout_runtime_topic, system_capabilities
from auto_scout.notifications import build_mission_success_payload
from auto_scout.notifications import build_preflight_refusal_payload
from auto_scout.notifications import companion_notification_webhook_url
from auto_scout.redaction import redact_sensitive
from config_utils import load_scout_config


DEFAULT_MISSION_START_MIN_BATTERY_LEVEL = 50.0
BATTERY_TOO_LOW_REASON = "battery_too_low_to_leave_dock"
NAVIGATION_SCAN_UNAVAILABLE_REASON = "navigation_scan_unavailable"
NAVIGATION_TF_UNAVAILABLE_REASON = "navigation_tf_unavailable"
REQUIRED_NAVIGATION_TF_EDGES = [
    ("odom", "base_link"),
    ("base_link", "base_laser"),
]


def _finite_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ["1", "true", "yes", "on"]


def evaluate_dock_departure_gate(battery_guard_state, mission_start_min_battery_level):
    payload = battery_guard_state if isinstance(battery_guard_state, dict) else {}
    mode = str(payload.get("mode") or "idle")
    charging = _as_bool(payload.get("charging"), default=(mode == "charging"))
    battery_percent = _finite_number(payload.get("battery_percent"))
    threshold = float(mission_start_min_battery_level)
    result = {
        "ok": True,
        "reason": "dock_departure_allowed",
        "battery_percent": battery_percent,
        "charging": charging,
        "battery_guard_mode": mode,
        "mission_start_min_battery_level": threshold,
        "battery_guard_state": payload,
    }
    if charging and battery_percent is not None and battery_percent < threshold:
        result["ok"] = False
        result["reason"] = BATTERY_TOO_LOW_REASON
    return result


def normalize_frame_id(frame_id):
    return str(frame_id or "").strip().lstrip("/")


def tf_edges_from_message(msg):
    edges = []
    for transform in getattr(msg, "transforms", []) or []:
        parent = normalize_frame_id(getattr(getattr(transform, "header", None), "frame_id", ""))
        child = normalize_frame_id(getattr(transform, "child_frame_id", ""))
        if parent and child:
            edges.append((parent, child))
    return edges


def format_tf_edges(edges):
    return [{"parent": parent, "child": child} for parent, child in sorted(edges)]


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
            from sensor_msgs.msg import CompressedImage, LaserScan
            from std_msgs.msg import String
        except ImportError as exc:
            raise MissionRunError("ROS mission controller requires ROS Python packages: {}".format(exc))
        try:
            from tf2_msgs.msg import TFMessage
        except ImportError:
            TFMessage = None

        self.actionlib = actionlib
        self.rospy = rospy
        self.GoalStatus = GoalStatus
        self.MoveBaseAction = MoveBaseAction
        self.MoveBaseGoal = MoveBaseGoal
        self.String = String
        self.TFMessage = TFMessage

        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)
        self.mission, self.mission_path = load_mission_config(mission_path)

        self.artifact_dir = Path(artifact_dir) if artifact_dir else Path.cwd() / "artifacts" / "runs" / "remote-smoke-loop"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.artifact_dir / "mission.log"

        self.latest_image = None
        self.latest_pose = None
        self.pose_seen = False
        self.latest_battery_guard_state = None
        self.scan_seen = False
        self.tf_edges = set()

        rospy.init_node("scout_navigation_controller", anonymous=False)
        self.status_pub = rospy.Publisher("/scout/mission_status", String, queue_size=1)
        self.dock_pub = rospy.Publisher("/scout/runtime/request", String, queue_size=1)
        rospy.Subscriber(
            scout_runtime_topic(self.site_config, self.config, "camera_compressed", "/camera/image_raw/compressed"),
            CompressedImage,
            self.camera_callback,
            queue_size=1,
        )
        rospy.Subscriber(
            scout_runtime_topic(self.site_config, self.config, "lidar_scan", "/scan"),
            LaserScan,
            self.scan_callback,
            queue_size=1,
        )
        rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, self.pose_callback, queue_size=1)
        rospy.Subscriber("/odom", Odometry, self.odom_callback, queue_size=1)
        rospy.Subscriber(
            scout_runtime_topic(self.site_config, self.config, "battery_guard_state", "/scout/battery_guard_state"),
            String,
            self.battery_guard_callback,
            queue_size=1,
        )
        if TFMessage is not None:
            rospy.Subscriber("/tf", TFMessage, self.tf_callback, queue_size=10)
            rospy.Subscriber("/tf_static", TFMessage, self.tf_callback, queue_size=10)
        else:
            rospy.logwarn("tf2_msgs is unavailable; mapped mission preflight will block until TF support is installed")
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
            json.dump(redact_sensitive(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def publish_status_payload(self, payload):
        self.status_pub.publish(json.dumps(redact_sensitive(payload), sort_keys=True))

    def camera_callback(self, msg):
        self.latest_image = msg

    def scan_callback(self, msg):
        self.scan_seen = True

    def tf_callback(self, msg):
        for edge in tf_edges_from_message(msg):
            self.tf_edges.add(edge)

    def battery_guard_callback(self, msg):
        try:
            payload = json.loads(getattr(msg, "data", "") or "{}")
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            self.latest_battery_guard_state = payload

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

    def wait_for_battery_guard_state(self, timeout_seconds=3.0):
        start = self.rospy.Time.now()
        while not self.rospy.is_shutdown():
            if self.latest_battery_guard_state is not None:
                return self.latest_battery_guard_state
            if (self.rospy.Time.now() - start).to_sec() >= timeout_seconds:
                return None
            self.rospy.sleep(0.25)

    def mission_start_min_battery_level(self):
        safety = self.config.get("safety", {}) if isinstance(self.config.get("safety", {}), dict) else {}
        return float(safety.get("mission_start_min_battery_level", DEFAULT_MISSION_START_MIN_BATTERY_LEVEL))

    def evaluate_mission_start_preflight(self):
        state = self.wait_for_battery_guard_state()
        battery_gate = evaluate_dock_departure_gate(state, self.mission_start_min_battery_level())
        if not battery_gate["ok"]:
            return battery_gate
        navigation_gate = self.evaluate_navigation_preflight()
        if not navigation_gate["ok"]:
            return navigation_gate
        battery_gate["navigation"] = navigation_gate
        return battery_gate

    def navigation_input_state(self):
        required_edges = set(REQUIRED_NAVIGATION_TF_EDGES)
        missing_edges = required_edges.difference(self.tf_edges)
        result = {
            "ok": True,
            "reason": "navigation_inputs_available",
            "scan_seen": self.scan_seen,
            "tf_edges": format_tf_edges(self.tf_edges),
            "required_tf_edges": format_tf_edges(required_edges),
            "missing_tf_edges": format_tf_edges(missing_edges),
        }
        if not self.scan_seen:
            result["ok"] = False
            result["reason"] = NAVIGATION_SCAN_UNAVAILABLE_REASON
            return result
        if self.TFMessage is None or missing_edges:
            result["ok"] = False
            result["reason"] = NAVIGATION_TF_UNAVAILABLE_REASON
            return result
        return result

    def evaluate_navigation_preflight(self, timeout_seconds=5.0):
        start = self.rospy.Time.now()
        while not self.rospy.is_shutdown():
            state = self.navigation_input_state()
            if state["ok"]:
                return state
            if (self.rospy.Time.now() - start).to_sec() >= timeout_seconds:
                return state
            self.rospy.sleep(0.25)

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

        webhook_url = self.notification_webhook_url()
        if not webhook_url:
            raise MissionRunError("Notification is enabled but no webhook URL is configured")
        if not REQUESTS_AVAILABLE:
            raise MissionRunError("Notification requires the requests package")

        payload = build_mission_success_payload(
            self.mission.get("name", "smoke_loop"),
            str(self.artifact_dir),
            photo_path,
            return_result,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        response = requests.post(webhook_url, json=payload, timeout=15)
        response.raise_for_status()
        self.log("Sent Slack mission notification")
        return {"sent": True, "status_code": response.status_code}

    def notification_webhook_url(self):
        return companion_notification_webhook_url(self.site_config)

    def send_preflight_notification(self, result):
        webhook_url = self.notification_webhook_url()
        if not webhook_url:
            return {"sent": False, "reason": "webhook_url_empty"}
        payload = build_preflight_refusal_payload(result)
        try:
            response = requests.post(webhook_url, json=payload, timeout=15)
            response.raise_for_status()
        except Exception as exc:
            return {"sent": False, "reason": "webhook_error", "error": redact_sensitive(str(exc))}
        self.log("Sent Slack preflight notification")
        return {"sent": True, "status_code": response.status_code}

    def refuse_mission_start(self, gate):
        result = {
            "ok": False,
            "phase": "preflight",
            "mission": self.mission.get("name", "smoke_loop"),
            "reason": gate.get("reason", "preflight_failed"),
            "artifact_dir": str(self.artifact_dir),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        for key, value in gate.items():
            if key not in ["ok", "reason"]:
                result[key] = value

        if result["reason"] == BATTERY_TOO_LOW_REASON:
            self.log(
                "Mission blocked: battery {:.1f}% is below mission start threshold {:.1f}%".format(
                    result["battery_percent"],
                    result["mission_start_min_battery_level"],
                )
            )
        else:
            self.log("Mission blocked: {}".format(result["reason"]))
        result["notification"] = self.send_preflight_notification(result)
        self.write_json("mission-result.json", result)
        self.publish_status_payload(result)
        return result

    def run_smoke_loop(self):
        self.log("Starting smoke-loop mission")
        mission_start_gate = self.evaluate_mission_start_preflight()
        if not mission_start_gate["ok"]:
            return self.refuse_mission_start(mission_start_gate)

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
    print(json.dumps(redact_sensitive(result), indent=2, sort_keys=True))
    return 0

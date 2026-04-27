#!/usr/bin/env python
"""Companion-side map return controller for low-battery docking."""

from __future__ import print_function

import argparse
import json
import math
import os
import threading

from config_utils import load_scout_config
from scout_runtime_config import load_site_config
from scout_runtime_config import scout_runtime_topic


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ["1", "true", "yes", "on"]


def _finite_number(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _json_payload(text):
    try:
        payload = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class BatteryMapReturnLogic(object):
    """Pure eligibility checks for companion map-assisted return."""

    def __init__(self, localization_mode=False, dock_waypoint="charging_station", waypoints=None, pose_stale_timeout=3.0):
        self.localization_mode = bool(localization_mode)
        self.dock_waypoint = dock_waypoint
        self.waypoints = waypoints or {}
        self.pose_stale_timeout = float(pose_stale_timeout)

    def has_dock_waypoint(self):
        return bool(self.dock_waypoint and self.dock_waypoint in self.waypoints)

    def pose_is_fresh(self, now, last_pose_time):
        if last_pose_time is None:
            return False
        return max(0.0, now - last_pose_time) <= self.pose_stale_timeout

    def can_claim(self, move_base_available, now, last_pose_time):
        if not self.localization_mode:
            return False, "localization_mode_disabled"
        if not self.has_dock_waypoint():
            return False, "dock_waypoint_missing"
        if not self.pose_is_fresh(now, last_pose_time):
            return False, "pose_stale"
        if not move_base_available:
            return False, "move_base_unavailable"
        return True, "map_return_ready"


class BatteryMapReturnController(object):
    """ROS node that claims low-battery map return when companion navigation is healthy."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import actionlib
            import rospy
            from actionlib_msgs.msg import GoalStatus
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from move_base_msgs.msg import MoveBaseAction
            from move_base_msgs.msg import MoveBaseGoal
            from nav_msgs.msg import Odometry
            from std_msgs.msg import String
        except ImportError as exc:
            raise SystemExit("Battery map return controller requires ROS Python packages: {}".format(exc))

        self.actionlib = actionlib
        self.rospy = rospy
        self.GoalStatus = GoalStatus
        self.MoveBaseAction = MoveBaseAction
        self.MoveBaseGoal = MoveBaseGoal
        self.String = String

        rospy.init_node("battery_map_return_controller", anonymous=False)
        config_path = rospy.get_param("~config_file", config_path)
        site_path = rospy.get_param("~site_file", site_path)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)

        safety = self.config.get("safety", {})
        navigation = self.config.get("navigation", {})
        localization_default = os.environ.get("AUTO_SCOUT_LOCALIZATION_MODE", "false")
        self.localization_mode = _as_bool(
            rospy.get_param("~localization_mode", localization_default),
            False,
        )
        self.dock_waypoint = rospy.get_param(
            "~dock_approach_waypoint",
            navigation.get("dock_approach_waypoint", "charging_station"),
        )
        self.dock_timeout = float(
            rospy.get_param(
                "~dock_approach_timeout_seconds",
                navigation.get("dock_approach_timeout_seconds", safety.get("map_return_timeout_seconds", 180.0)),
            )
        )
        self.pose_stale_timeout = float(
            rospy.get_param("~pose_stale_timeout", navigation.get("pose_stale_timeout", 3.0))
        )
        self.move_base_wait_seconds = float(rospy.get_param("~move_base_wait_seconds", 1.0))

        self.logic = BatteryMapReturnLogic(
            localization_mode=self.localization_mode,
            dock_waypoint=self.dock_waypoint,
            waypoints=self.config.get("waypoints", {}),
            pose_stale_timeout=self.pose_stale_timeout,
        )

        self.state_topic = rospy.get_param(
            "~state_topic",
            scout_runtime_topic(self.site_config, self.config, "battery_guard_state", "/scout/battery_guard_state"),
        )
        self.control_topic = rospy.get_param(
            "~control_topic",
            scout_runtime_topic(self.site_config, self.config, "battery_guard_control", "/scout/battery_guard_control"),
        )

        self.last_pose_time = None
        self.latest_guard_state = {}
        self.return_in_progress = False
        self.lock = threading.Lock()

        self.move_base_client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        self.control_pub = rospy.Publisher(self.control_topic, String, queue_size=1)
        self.state_sub = rospy.Subscriber(self.state_topic, String, self.guard_state_callback, queue_size=1)
        self.amcl_sub = rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, self.pose_callback, queue_size=1)
        self.odom_sub = rospy.Subscriber("/odom", Odometry, self.pose_callback, queue_size=1)

    def _now_seconds(self):
        return self.rospy.Time.now().to_sec()

    def pose_callback(self, msg):
        self.last_pose_time = self._now_seconds()

    def _publish_control(self, action, reason):
        payload = {"action": action, "reason": reason}
        self.control_pub.publish(json.dumps(payload, sort_keys=True))

    def _move_base_available(self):
        return self.move_base_client.wait_for_server(self.rospy.Duration(self.move_base_wait_seconds))

    def guard_state_callback(self, msg):
        payload = _json_payload(getattr(msg, "data", ""))
        self.latest_guard_state = payload
        if payload.get("mode") != "return_required" or not payload.get("active", False):
            return
        with self.lock:
            if self.return_in_progress:
                return
            self.return_in_progress = True
        thread = threading.Thread(target=self._run_map_return)
        thread.daemon = True
        thread.start()

    def _dock_goal(self):
        waypoint = self.config.get("waypoints", {}).get(self.dock_waypoint, {})
        goal = self.MoveBaseGoal()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = self.rospy.Time.now()
        goal.target_pose.pose.position.x = waypoint["x"]
        goal.target_pose.pose.position.y = waypoint["y"]
        goal.target_pose.pose.orientation.z = waypoint["z"]
        goal.target_pose.pose.orientation.w = waypoint["w"]
        return goal

    def _run_map_return(self):
        try:
            now = self._now_seconds()
            move_base_available = self._move_base_available()
            can_claim, reason = self.logic.can_claim(move_base_available, now, self.last_pose_time)
            if not can_claim:
                self.rospy.logwarn("Not claiming battery map return: %s", reason)
                return

            self._publish_control("claim_map_return", reason)
            self.move_base_client.cancel_all_goals()
            self.rospy.sleep(0.2)
            self.move_base_client.send_goal(self._dock_goal())

            deadline = self.rospy.Time.now() + self.rospy.Duration(self.dock_timeout)
            rate = self.rospy.Rate(5.0)
            while not self.rospy.is_shutdown():
                guard_mode = self.latest_guard_state.get("mode")
                if guard_mode not in ["return_required", "map_return"]:
                    self.move_base_client.cancel_goal()
                    return
                if self.move_base_client.wait_for_result(self.rospy.Duration(0.0)):
                    break
                if self.rospy.Time.now() >= deadline:
                    self.move_base_client.cancel_goal()
                    self._publish_control("map_return_failed", "map_return_timeout")
                    return
                rate.sleep()

            state = self.move_base_client.get_state()
            if state == self.GoalStatus.SUCCEEDED:
                self._publish_control("start_vendor_dock", "map_return_succeeded")
            else:
                self.move_base_client.cancel_goal()
                self._publish_control("map_return_failed", "map_return_failed_state_{}".format(state))
        finally:
            with self.lock:
                self.return_in_progress = False

    def run(self):
        self.rospy.loginfo(
            "Battery map return controller active: localization_mode=%s dock_waypoint=%s",
            self.localization_mode,
            self.dock_waypoint,
        )
        self.rospy.spin()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    controller = BatteryMapReturnController(config_path=args.config, site_path=args.site)
    controller.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

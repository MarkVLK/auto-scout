#!/usr/bin/env python
"""Scout-local low-battery return-to-dock guard."""

from __future__ import print_function

import argparse
import json
import math
import threading

from scout_runtime_config import scout_runtime_topic
from scout_node_utils import load_runtime_configs
from scout_node_utils import private_param


MODE_IDLE = "idle"
MODE_RETURN_REQUIRED = "return_required"
MODE_MAP_RETURN = "map_return"
MODE_VENDOR_DOCKING = "vendor_docking"
MODE_CHARGING = "charging"
MODE_FAILED = "failed"

ACTION_CALL_VENDOR_DOCK = "call_vendor_dock"

VENDOR_STATUS_DETECT = 1
VENDOR_STATUS_ALIGN = 2
VENDOR_STATUS_BACK = 3
VENDOR_STATUS_SUCCESS = 4
VENDOR_STATUS_FAIL = 5
VENDOR_STATUS_INACTIVE = 6
VENDOR_STATUS_CANCEL = 7
VENDOR_STATUS_REDETECT = 8

ACTIVE_VENDOR_STATUSES = set(
    [VENDOR_STATUS_DETECT, VENDOR_STATUS_ALIGN, VENDOR_STATUS_BACK, VENDOR_STATUS_REDETECT]
)


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


def _battery_percent(value):
    """Return a plausible battery percent, or ``None`` if the reading is junk.

    The vendor ``roller_eye/status`` array layout is inferred from rooted
    inspection, not from a documented contract. If a firmware update reorders
    it we would silently read some other field: a low value docks the robot
    mid-mission, a high value means it never returns and runs flat. Refusing to
    act on out-of-range values is the safe response to both.
    """
    numeric = _finite_number(value)
    if numeric is None:
        return None
    if numeric < 0.0 or numeric > 100.0:
        return None
    return numeric


def _json_payload(text):
    try:
        payload = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class ScoutBatteryDockGuardLogic(object):
    """Pure low-battery docking state machine."""

    def __init__(
        self,
        min_battery_level=20.0,
        critical_battery_level=10.0,
        battery_reset_margin=5.0,
        map_return_claim_timeout_seconds=5.0,
        map_return_timeout_seconds=180.0,
        dock_timeout_seconds=180.0,
        dock_retry_count=1,
    ):
        self.min_battery_level = float(min_battery_level)
        self.critical_battery_level = float(critical_battery_level)
        self.battery_reset_margin = float(battery_reset_margin)
        self.map_return_claim_timeout_seconds = float(map_return_claim_timeout_seconds)
        self.map_return_timeout_seconds = float(map_return_timeout_seconds)
        self.dock_timeout_seconds = float(dock_timeout_seconds)
        self.dock_retry_count = int(dock_retry_count)

        self.mode = MODE_IDLE
        self.reason = "battery_above_threshold"
        self.battery_percent = None
        self.rejected_battery_reading = None
        self.charging = False
        self.attempt = 0
        self.last_vendor_status = None
        self.claim_deadline = None
        self.map_return_deadline = None
        self.vendor_deadline = None

    def state_payload(self):
        return {
            "mode": self.mode,
            "active": self.mode in [MODE_RETURN_REQUIRED, MODE_MAP_RETURN, MODE_VENDOR_DOCKING, MODE_CHARGING, MODE_FAILED],
            "battery_percent": self.battery_percent,
            "charging": self.charging,
            "reason": self.reason,
            "attempt": self.attempt,
            "last_vendor_status": self.last_vendor_status,
            "rejected_battery_reading": self.rejected_battery_reading,
        }

    def _set_mode(self, mode, reason):
        self.mode = mode
        self.reason = reason

    def _reset_to_idle_if_recovered(self):
        if self.battery_percent is None:
            return
        # Never abandon a return that is already under way. Battery percent
        # derived from voltage routinely recovers several points the moment
        # load drops, which is exactly what happens as the robot slows to dock.
        # Resetting here would stop tracking a dock that is still physically in
        # progress and let the safety filter unblock planner commands, putting
        # two controllers on one robot.
        if self.mode in [MODE_MAP_RETURN, MODE_VENDOR_DOCKING]:
            return
        if self.battery_percent >= self.min_battery_level + self.battery_reset_margin:
            self._set_mode(MODE_IDLE, "battery_recovered")
            self.attempt = 0
            self.claim_deadline = None
            self.map_return_deadline = None
            self.vendor_deadline = None

    def _start_vendor_docking(self, now, reason):
        self.attempt += 1
        self._set_mode(MODE_VENDOR_DOCKING, reason)
        self.claim_deadline = None
        self.map_return_deadline = None
        self.vendor_deadline = now + self.dock_timeout_seconds
        return [ACTION_CALL_VENDOR_DOCK]

    def _retry_or_fail(self, now, reason):
        if self.attempt <= self.dock_retry_count:
            return self._start_vendor_docking(now, reason)
        self._set_mode(MODE_FAILED, reason)
        self.claim_deadline = None
        self.map_return_deadline = None
        self.vendor_deadline = None
        return []

    def _trigger_return(self, now, reason):
        if self.mode in [MODE_RETURN_REQUIRED, MODE_MAP_RETURN, MODE_VENDOR_DOCKING, MODE_CHARGING, MODE_FAILED]:
            return []
        if self.battery_percent is not None and self.battery_percent <= self.critical_battery_level:
            return self._start_vendor_docking(now, "critical_battery_vendor_dock")
        self._set_mode(MODE_RETURN_REQUIRED, reason)
        self.claim_deadline = now + self.map_return_claim_timeout_seconds
        self.map_return_deadline = None
        self.vendor_deadline = None
        return []

    def handle_battery(self, battery_percent, charging, now):
        numeric = _battery_percent(battery_percent)
        if numeric is not None:
            self.battery_percent = numeric
            self.rejected_battery_reading = None
        elif battery_percent is not None:
            # Hold the last plausible value rather than acting on a bad one.
            self.rejected_battery_reading = battery_percent
        self.charging = bool(charging)

        if self.charging:
            self._set_mode(MODE_CHARGING, "charging_detected")
            self.attempt = 0
            self.claim_deadline = None
            self.map_return_deadline = None
            self.vendor_deadline = None
            return []

        self._reset_to_idle_if_recovered()
        if self.battery_percent is None:
            return []
        if self.battery_percent <= self.min_battery_level:
            if self.mode == MODE_RETURN_REQUIRED and self.battery_percent <= self.critical_battery_level:
                return self._start_vendor_docking(now, "critical_battery_vendor_dock")
            return self._trigger_return(now, "low_battery_return_required")
        return []

    def handle_control(self, payload, now):
        action = str(payload.get("action", "")).strip()
        reason = str(payload.get("reason", "") or action)
        if action == "claim_map_return":
            if self.mode != MODE_RETURN_REQUIRED:
                return []
            if self.claim_deadline is not None and now > self.claim_deadline:
                return []
            self._set_mode(MODE_MAP_RETURN, reason or "companion_map_return_claimed")
            self.claim_deadline = None
            self.map_return_deadline = now + self.map_return_timeout_seconds
            return []

        if action == "start_vendor_dock":
            if self.mode in [MODE_IDLE, MODE_RETURN_REQUIRED, MODE_MAP_RETURN]:
                return self._start_vendor_docking(now, reason or "vendor_dock_requested")
            return []

        if action == "map_return_failed":
            if self.mode == MODE_MAP_RETURN:
                return self._start_vendor_docking(now, reason or "map_return_failed")
            return []

        return []

    def handle_vendor_status(self, status, now):
        try:
            numeric_status = int(status)
        except (TypeError, ValueError):
            return []
        self.last_vendor_status = numeric_status

        if numeric_status in ACTIVE_VENDOR_STATUSES:
            if self.mode in [MODE_RETURN_REQUIRED, MODE_MAP_RETURN]:
                self._set_mode(MODE_VENDOR_DOCKING, "vendor_docking_active")
                self.claim_deadline = None
                self.map_return_deadline = None
                self.vendor_deadline = now + self.dock_timeout_seconds
            return []

        if numeric_status == VENDOR_STATUS_SUCCESS:
            self._set_mode(MODE_CHARGING, "vendor_dock_success")
            self.claim_deadline = None
            self.map_return_deadline = None
            self.vendor_deadline = None
            return []

        if numeric_status in [VENDOR_STATUS_FAIL, VENDOR_STATUS_CANCEL]:
            if self.mode == MODE_VENDOR_DOCKING:
                return self._retry_or_fail(now, "vendor_dock_failed")
        return []

    def handle_vendor_call_failed(self, now):
        return self._retry_or_fail(now, "vendor_dock_service_call_failed")

    def tick(self, now):
        if self.mode == MODE_RETURN_REQUIRED and self.claim_deadline is not None and now >= self.claim_deadline:
            return self._start_vendor_docking(now, "map_return_claim_timeout")
        if self.mode == MODE_MAP_RETURN and self.map_return_deadline is not None and now >= self.map_return_deadline:
            return self._start_vendor_docking(now, "map_return_timeout")
        if self.mode == MODE_VENDOR_DOCKING and self.vendor_deadline is not None and now >= self.vendor_deadline:
            return self._retry_or_fail(now, "vendor_dock_timeout")
        return []


class ScoutBatteryDockGuardNode(object):
    """ROS wrapper for the Scout-local low-battery docking guard."""

    def __init__(
        self,
        config_path=None,
        site_path=None,
        config=None,
        site_config=None,
        init_node=True,
        param_prefix=None,
    ):
        try:
            import rospy
            from std_msgs.msg import Int32
            from std_msgs.msg import String
            from roller_eye.msg import status as BatteryStatus
            from roller_eye.srv import nav_low_bat
        except ImportError as exc:
            raise SystemExit("Scout battery dock guard requires ROS/vendor packages: {}".format(exc))

        self.rospy = rospy
        self.Int32 = Int32
        self.String = String
        self.BatteryStatus = BatteryStatus
        self.nav_low_bat = nav_low_bat

        # Four subscribers plus the tick timer all mutate self.logic from
        # separate rospy threads. Unsynchronized, concurrent entry into
        # _start_vendor_docking can double-call /nav_low_bat or skip a retry.
        # Re-entrant because the vendor-call failure path re-enters _run_actions.
        self.state_lock = threading.RLock()

        if init_node:
            rospy.init_node("scout_battery_dock_guard", anonymous=False)
        self.config, self.config_path, self.site_config, self.site_path = load_runtime_configs(
            rospy,
            config_path=config_path,
            site_path=site_path,
            config=config,
            site_config=site_config,
            param_prefix=param_prefix,
        )
        safety = self.config.get("safety", {})

        self.enabled = _as_bool(
            rospy.get_param(private_param(param_prefix, "enabled"), safety.get("battery_guard_enabled", True)),
            True,
        )
        self.dry_run = _as_bool(
            rospy.get_param(private_param(param_prefix, "dry_run"), safety.get("battery_guard_dry_run", False)),
            False,
        )
        self.logic = ScoutBatteryDockGuardLogic(
            min_battery_level=rospy.get_param(
                private_param(param_prefix, "min_battery_level"),
                safety.get("min_battery_level", 20.0),
            ),
            critical_battery_level=rospy.get_param(
                private_param(param_prefix, "critical_battery_level"),
                safety.get("critical_battery_level", 10.0),
            ),
            battery_reset_margin=rospy.get_param(
                private_param(param_prefix, "battery_reset_margin"),
                safety.get("battery_reset_margin", 5.0),
            ),
            map_return_claim_timeout_seconds=rospy.get_param(
                private_param(param_prefix, "map_return_claim_timeout_seconds"),
                safety.get("map_return_claim_timeout_seconds", 5.0),
            ),
            map_return_timeout_seconds=rospy.get_param(
                private_param(param_prefix, "map_return_timeout_seconds"),
                safety.get("map_return_timeout_seconds", 180.0),
            ),
            dock_timeout_seconds=rospy.get_param(
                private_param(param_prefix, "dock_timeout_seconds"),
                safety.get("dock_timeout_seconds", 180.0),
            ),
            dock_retry_count=rospy.get_param(
                private_param(param_prefix, "dock_retry_count"),
                safety.get("dock_retry_count", 1),
            ),
        )

        self.battery_topic = rospy.get_param(
            private_param(param_prefix, "battery_topic"),
            scout_runtime_topic(self.site_config, self.config, "battery_status", "/SensorNode/simple_battery_status"),
        )
        self.vendor_status_topic = rospy.get_param(
            private_param(param_prefix, "vendor_status_topic"),
            scout_runtime_topic(self.site_config, self.config, "vendor_dock_status", "/CoreNode/going_home_status"),
        )
        self.state_topic = rospy.get_param(
            private_param(param_prefix, "state_topic"),
            scout_runtime_topic(self.site_config, self.config, "battery_guard_state", "/scout/battery_guard_state"),
        )
        self.control_topic = rospy.get_param(
            private_param(param_prefix, "control_topic"),
            scout_runtime_topic(self.site_config, self.config, "battery_guard_control", "/scout/battery_guard_control"),
        )
        self.runtime_request_topic = rospy.get_param(
            private_param(param_prefix, "runtime_request_topic"),
            scout_runtime_topic(self.site_config, self.config, "runtime_request", "/scout/runtime/request"),
        )
        self.vendor_dock_service = rospy.get_param(private_param(param_prefix, "vendor_dock_service"), "/nav_low_bat")
        self.publish_hz = float(
            rospy.get_param(private_param(param_prefix, "publish_hz"), safety.get("battery_guard_publish_hz", 1.0))
        )

        self.state_pub = rospy.Publisher(self.state_topic, String, queue_size=1, latch=True)
        self.battery_sub = rospy.Subscriber(self.battery_topic, BatteryStatus, self.battery_callback, queue_size=1)
        self.vendor_status_sub = rospy.Subscriber(
            self.vendor_status_topic,
            Int32,
            self.vendor_status_callback,
            queue_size=1,
        )
        self.control_sub = rospy.Subscriber(self.control_topic, String, self.control_callback, queue_size=1)
        self.runtime_request_sub = rospy.Subscriber(
            self.runtime_request_topic,
            String,
            self.runtime_request_callback,
            queue_size=1,
        )
        self.vendor_dock_proxy = rospy.ServiceProxy(self.vendor_dock_service, nav_low_bat)

    def _now_seconds(self):
        return self.rospy.Time.now().to_sec()

    def _publish_state(self):
        payload = self.logic.state_payload()
        payload["enabled"] = self.enabled
        payload["dry_run"] = self.dry_run
        self.state_pub.publish(json.dumps(payload, sort_keys=True))

    def _run_actions(self, actions):
        # Drained iteratively rather than recursively: each failed vendor call
        # blocks up to 2s in wait_for_service, and recursion made that stack
        # depth scale with dock_retry_count inside a subscriber callback.
        pending = list(actions)
        while pending:
            action = pending.pop(0)
            if action == ACTION_CALL_VENDOR_DOCK:
                pending.extend(self._call_vendor_dock())
        self._publish_state()

    def _call_vendor_dock(self):
        """Call the vendor dock service, returning any follow-up actions."""
        if self.dry_run:
            self.rospy.logwarn("Battery guard dry-run: skipping %s", self.vendor_dock_service)
            return []
        try:
            self.rospy.wait_for_service(self.vendor_dock_service, timeout=2.0)
            self.vendor_dock_proxy()
        except Exception as exc:
            self.rospy.logerr("Vendor dock request failed: %s", exc)
            return self.logic.handle_vendor_call_failed(self._now_seconds())
        return []

    def battery_callback(self, msg):
        if not self.enabled:
            return
        values = list(getattr(msg, "status", []) or [])
        battery_percent = values[1] if len(values) > 1 else None
        charging = bool(values[2]) if len(values) > 2 else False
        with self.state_lock:
            self._run_actions(self.logic.handle_battery(battery_percent, charging, self._now_seconds()))
            rejected = self.logic.rejected_battery_reading
        if rejected is not None:
            self.rospy.logwarn_throttle(
                60.0,
                "Ignoring implausible battery reading %s from %s; vendor status array may have changed layout",
                rejected,
                self.battery_topic,
            )

    def vendor_status_callback(self, msg):
        if not self.enabled:
            return
        with self.state_lock:
            self._run_actions(self.logic.handle_vendor_status(getattr(msg, "data", None), self._now_seconds()))

    def control_callback(self, msg):
        if not self.enabled:
            return
        with self.state_lock:
            self._run_actions(self.logic.handle_control(_json_payload(getattr(msg, "data", "")), self._now_seconds()))

    def runtime_request_callback(self, msg):
        if not self.enabled:
            return
        if str(getattr(msg, "data", "")).strip().lower() != "dock":
            return
        payload = {"action": "start_vendor_dock", "reason": "runtime_request"}
        with self.state_lock:
            self._run_actions(self.logic.handle_control(payload, self._now_seconds()))

    def log_active(self):
        self.rospy.loginfo(
            "Scout battery dock guard active: battery=%s state=%s control=%s vendor_status=%s",
            self.battery_topic,
            self.state_topic,
            self.control_topic,
            self.vendor_status_topic,
        )

    def tick(self, event=None):
        if not self.enabled:
            return
        with self.state_lock:
            self._run_actions(self.logic.tick(self._now_seconds()))

    def run(self):
        self.log_active()
        rate = self.rospy.Rate(self.publish_hz)
        while not self.rospy.is_shutdown():
            self.tick()
            rate.sleep()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    node = ScoutBatteryDockGuardNode(config_path=args.config, site_path=args.site)
    node.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

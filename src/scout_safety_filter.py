#!/usr/bin/env python2
"""Gate planner velocity commands with Scout-local safety sensors."""

from __future__ import print_function

import argparse
import json
import math
import threading

from scout_runtime_config import scout_runtime_topic
from scout_node_utils import load_runtime_configs
from scout_node_utils import private_param


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


class ScoutSafetyLogic(object):
    """Pure command-gating logic shared by the ROS node and unit tests."""

    def __init__(
        self,
        twist_type=None,
        tof_stop_enabled=True,
        require_tof=False,
        max_obstacle_distance=0.3,
        emergency_stop_distance=0.15,
        tof_stale_timeout=1.0,
        scan_watchdog_enabled=True,
        scan_stale_timeout=1.0,
        caution_speed=0.05,
        mission_start_min_battery_level=50.0,
    ):
        self.twist_type = twist_type
        self.tof_stop_enabled = bool(tof_stop_enabled)
        self.require_tof = bool(require_tof)
        self.max_obstacle_distance = float(max_obstacle_distance)
        self.emergency_stop_distance = float(emergency_stop_distance)
        self.tof_stale_timeout = float(tof_stale_timeout)
        self.scan_watchdog_enabled = bool(scan_watchdog_enabled)
        self.scan_stale_timeout = float(scan_stale_timeout)
        self.caution_speed = float(caution_speed)
        self.mission_start_min_battery_level = float(mission_start_min_battery_level)
        self.battery_guard_block_modes = set(["return_required", "vendor_docking", "failed"])

    def _new_twist(self, template):
        twist_type = self.twist_type or template.__class__
        return twist_type()

    def copy_twist(self, template):
        result = self._new_twist(template)
        result.linear.x = template.linear.x
        result.linear.y = template.linear.y
        result.linear.z = template.linear.z
        result.angular.x = template.angular.x
        result.angular.y = template.angular.y
        result.angular.z = template.angular.z
        return result

    def zero_twist(self, template):
        result = self._new_twist(template)
        result.linear.x = 0.0
        result.linear.y = 0.0
        result.linear.z = 0.0
        result.angular.x = 0.0
        result.angular.y = 0.0
        result.angular.z = 0.0
        return result

    def _decision(
        self,
        command,
        state,
        blocked,
        reason,
        tof_range,
        tof_age,
        scan_age,
        battery_percent=None,
        charging=False,
    ):
        return {
            "command": command,
            "state": state,
            "blocked": bool(blocked),
            "reason": reason,
            "tof_range": tof_range,
            "tof_age": tof_age,
            "scan_age": scan_age,
            "battery_percent": battery_percent,
            "charging": bool(charging),
            "mission_start_min_battery_level": self.mission_start_min_battery_level,
        }

    def decide(
        self,
        command,
        tof_seen=False,
        tof_range=None,
        tof_age=None,
        scan_seen=False,
        scan_age=None,
        battery_guard_mode=None,
        battery_percent=None,
        charging=False,
    ):
        """Return a command decision for the latest planner command and sensor ages."""
        numeric_tof = _finite_number(tof_range)
        numeric_battery = _finite_number(battery_percent)
        guard_mode = str(battery_guard_mode or "idle")
        is_charging = _as_bool(charging, default=(guard_mode == "charging"))

        if guard_mode in self.battery_guard_block_modes:
            return self._decision(
                self.zero_twist(command),
                "battery_guard_{}".format(guard_mode),
                True,
                "Battery guard is controlling return-to-dock",
                numeric_tof,
                tof_age,
                scan_age,
                battery_percent=numeric_battery,
                charging=is_charging,
            )

        if is_charging and numeric_battery is not None and numeric_battery < self.mission_start_min_battery_level:
            return self._decision(
                self.zero_twist(command),
                "dock_charge_required",
                True,
                "Scout is charging below the mission start battery threshold",
                numeric_tof,
                tof_age,
                scan_age,
                battery_percent=numeric_battery,
                charging=is_charging,
            )

        if self.scan_watchdog_enabled:
            if not scan_seen:
                return self._decision(
                    self.zero_twist(command),
                    "scan_unavailable",
                    True,
                    "LiDAR scan has not been observed",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )
            if scan_age is not None and scan_age > self.scan_stale_timeout:
                return self._decision(
                    self.zero_twist(command),
                    "scan_stale",
                    True,
                    "LiDAR scan is stale",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )

        if self.tof_stop_enabled:
            if not tof_seen:
                if self.require_tof:
                    return self._decision(
                        self.zero_twist(command),
                        "tof_unavailable",
                        True,
                        "Required ToF range has not been observed",
                        numeric_tof,
                        tof_age,
                        scan_age,
                        battery_percent=numeric_battery,
                        charging=is_charging,
                    )
                return self._decision(
                    self.copy_twist(command),
                    "tof_unavailable",
                    False,
                    "Optional ToF range has not been observed",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )
            if tof_age is not None and tof_age > self.tof_stale_timeout:
                return self._decision(
                    self.zero_twist(command),
                    "tof_stale",
                    True,
                    "Previously observed ToF range is stale",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )
            if numeric_tof is not None and numeric_tof <= self.emergency_stop_distance:
                return self._decision(
                    self.zero_twist(command),
                    "tof_stop",
                    True,
                    "ToF range is inside emergency stop distance",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )
            if numeric_tof is not None and numeric_tof <= self.max_obstacle_distance:
                result = self.copy_twist(command)
                if result.linear.x > self.caution_speed:
                    result.linear.x = self.caution_speed
                return self._decision(
                    result,
                    "tof_caution",
                    False,
                    "ToF range is inside caution distance",
                    numeric_tof,
                    tof_age,
                    scan_age,
                    battery_percent=numeric_battery,
                    charging=is_charging,
                )

        return self._decision(
            self.copy_twist(command),
            "clear",
            False,
            "Safety checks are clear",
            numeric_tof,
            tof_age,
            scan_age,
            battery_percent=numeric_battery,
            charging=is_charging,
        )


class ScoutCommandPublishPolicy(object):
    """Decide when the safety filter should take ownership of command output."""

    def __init__(self, command_stale_timeout=0.5):
        self.command_stale_timeout = float(command_stale_timeout)
        self.last_command_time = None
        self.was_command_active = False
        self.stop_sent_for_episode = False

    def command_age(self, now):
        if self.last_command_time is None:
            return None
        return max(0.0, float(now) - self.last_command_time)

    def is_command_active(self, now):
        age = self.command_age(now)
        return age is not None and age <= self.command_stale_timeout

    def note_command(self, now):
        if not self.is_command_active(now):
            self.stop_sent_for_episode = False
        self.last_command_time = float(now)

    def decide_publish(self, decision, now, command_event=False):
        age = self.command_age(now)
        command_active = age is not None and age <= self.command_stale_timeout
        stale_transition = self.was_command_active and not command_active
        publish = False
        publish_stop = False

        if command_active:
            if decision["blocked"]:
                if not self.stop_sent_for_episode:
                    publish = True
                    publish_stop = True
                    self.stop_sent_for_episode = True
            elif command_event:
                publish = True
                self.stop_sent_for_episode = False
        elif stale_transition and not self.stop_sent_for_episode:
            publish = True
            publish_stop = True
            self.stop_sent_for_episode = True

        command_suppressed = False
        if not publish:
            command_suppressed = bool(decision["blocked"] or stale_transition)

        self.was_command_active = command_active
        return {
            "publish": publish,
            "publish_stop": publish_stop,
            "command_active": command_active,
            "command_age": age,
            "command_suppressed": command_suppressed,
        }


class ScoutSafetyFilterNode(object):
    """ROS node that publishes only commands allowed by Scout-local safety checks."""

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
            from geometry_msgs.msg import Twist
            from sensor_msgs.msg import LaserScan
            from sensor_msgs.msg import Range
            from std_msgs.msg import String
        except ImportError as exc:
            raise SystemExit("Scout safety filter requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        self.Twist = Twist
        self.String = String
        if init_node:
            rospy.init_node("scout_safety_filter", anonymous=False)
        self.config, self.config_path, self.site_config, self.site_path = load_runtime_configs(
            rospy,
            config_path=config_path,
            site_path=site_path,
            config=config,
            site_config=site_config,
            param_prefix=param_prefix,
        )

        safety = self.config.get("safety", {})
        self.logic = ScoutSafetyLogic(
            twist_type=Twist,
            tof_stop_enabled=_as_bool(
                rospy.get_param(private_param(param_prefix, "tof_stop_enabled"), safety.get("tof_stop_enabled", True))
            ),
            require_tof=_as_bool(
                rospy.get_param(private_param(param_prefix, "require_tof"), safety.get("require_tof", False))
            ),
            max_obstacle_distance=rospy.get_param(
                private_param(param_prefix, "max_obstacle_distance"),
                safety.get("max_obstacle_distance", 0.3),
            ),
            emergency_stop_distance=rospy.get_param(
                private_param(param_prefix, "emergency_stop_distance"),
                safety.get("emergency_stop_distance", 0.15),
            ),
            tof_stale_timeout=rospy.get_param(
                private_param(param_prefix, "tof_stale_timeout"),
                safety.get("tof_stale_timeout", 1.0),
            ),
            scan_watchdog_enabled=_as_bool(
                rospy.get_param(
                    private_param(param_prefix, "scan_watchdog_enabled"),
                    safety.get("scan_watchdog_enabled", True),
                )
            ),
            scan_stale_timeout=rospy.get_param(
                private_param(param_prefix, "scan_stale_timeout"),
                safety.get("scan_stale_timeout", 1.0),
            ),
            caution_speed=rospy.get_param(
                private_param(param_prefix, "caution_speed"),
                safety.get("caution_speed", 0.05),
            ),
            mission_start_min_battery_level=rospy.get_param(
                private_param(param_prefix, "mission_start_min_battery_level"),
                safety.get("mission_start_min_battery_level", 50.0),
            ),
        )

        self.input_topic = rospy.get_param(
            private_param(param_prefix, "input_topic"),
            scout_runtime_topic(self.site_config, self.config, "planner_cmd_vel", "/scout/cmd_vel_planner"),
        )
        self.output_topic = rospy.get_param(
            private_param(param_prefix, "output_topic"),
            scout_runtime_topic(self.site_config, self.config, "autonomy_cmd_vel", "/scout/cmd_vel_companion"),
        )
        self.tof_topic = rospy.get_param(
            private_param(param_prefix, "tof_topic"),
            scout_runtime_topic(self.site_config, self.config, "tof_range", "/scout/tof"),
        )
        self.scan_topic = rospy.get_param(
            private_param(param_prefix, "scan_topic"),
            scout_runtime_topic(self.site_config, self.config, "lidar_scan", "/scan"),
        )
        self.state_topic = rospy.get_param(
            private_param(param_prefix, "state_topic"),
            scout_runtime_topic(self.site_config, self.config, "safety_state", "/scout/safety_state"),
        )
        self.battery_guard_state_topic = rospy.get_param(
            private_param(param_prefix, "battery_guard_state_topic"),
            scout_runtime_topic(self.site_config, self.config, "battery_guard_state", "/scout/battery_guard_state"),
        )
        self.publish_hz = float(
            rospy.get_param(private_param(param_prefix, "publish_hz"), safety.get("publish_hz", 10.0))
        )
        self.state_publish_period = float(rospy.get_param(private_param(param_prefix, "state_publish_period"), 1.0))
        self.command_policy = ScoutCommandPublishPolicy(
            rospy.get_param(private_param(param_prefix, "command_stale_timeout"), safety.get("command_stale_timeout", 0.5))
        )

        # rospy gives every subscriber its own thread and the publish timer
        # another. command_callback and tick both drive _publish_decision, which
        # mutates the episode state in ScoutCommandPublishPolicy. Interleaved,
        # the timer can consume the one-stop-per-episode budget so a real stop
        # is suppressed - the unsafe direction for a safety filter.
        # Re-entrant so command_callback can hold it across note_command and
        # the _publish_decision it triggers, keeping that pair atomic.
        self.state_lock = threading.RLock()

        self.latest_command = None
        self.tof_seen = False
        self.last_tof_range = None
        self.last_tof_time = None
        self.scan_seen = False
        self.last_scan_time = None
        self.battery_guard_mode = "idle"
        self.battery_percent = None
        self.charging = False
        self.last_state_json = None
        self.last_state_publish = None

        self.command_pub = rospy.Publisher(self.output_topic, Twist, queue_size=1)
        self.state_pub = rospy.Publisher(self.state_topic, String, queue_size=1)
        self.command_sub = rospy.Subscriber(self.input_topic, Twist, self.command_callback, queue_size=1)
        self.tof_sub = rospy.Subscriber(self.tof_topic, Range, self.tof_callback, queue_size=1)
        self.scan_sub = rospy.Subscriber(self.scan_topic, LaserScan, self.scan_callback, queue_size=1)
        self.battery_guard_sub = rospy.Subscriber(
            self.battery_guard_state_topic,
            String,
            self.battery_guard_callback,
            queue_size=1,
        )

    def _now(self):
        return self.rospy.Time.now()

    def _age(self, stamp, now):
        if stamp is None:
            return None
        return max(0.0, (now - stamp).to_sec())

    def command_callback(self, msg):
        now = self._now()
        with self.state_lock:
            self.latest_command = msg
            self.command_policy.note_command(now.to_sec())
            self._publish_decision(command_event=True, now=now)

    def tof_callback(self, msg):
        now = self._now()
        with self.state_lock:
            self.tof_seen = True
            self.last_tof_range = msg.range
            self.last_tof_time = now

    def scan_callback(self, msg):
        now = self._now()
        with self.state_lock:
            self.scan_seen = True
            self.last_scan_time = now

    def battery_guard_callback(self, msg):
        try:
            payload = json.loads(getattr(msg, "data", "") or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            return
        with self.state_lock:
            self.battery_guard_mode = str(payload.get("mode") or "idle")
            self.battery_percent = _finite_number(payload.get("battery_percent"))
            self.charging = _as_bool(payload.get("charging"), default=(self.battery_guard_mode == "charging"))

    def _state_payload(self, decision, publish_status):
        return {
            "state": decision["state"],
            "blocked": decision["blocked"],
            "reason": decision["reason"],
            "battery_guard_mode": self.battery_guard_mode,
            "battery_percent": decision["battery_percent"],
            "charging": decision["charging"],
            "mission_start_min_battery_level": decision["mission_start_min_battery_level"],
            "command_active": publish_status["command_active"],
            "command_age": publish_status["command_age"],
            "command_suppressed": publish_status["command_suppressed"],
            "tof_range": decision["tof_range"],
            "tof_age": decision["tof_age"],
            "scan_age": decision["scan_age"],
            "input_topic": self.input_topic,
            "output_topic": self.output_topic,
            "tof_topic": self.tof_topic,
            "scan_topic": self.scan_topic,
        }

    def _publish_state(self, decision, publish_status, now, force=False):
        payload_json = json.dumps(self._state_payload(decision, publish_status), sort_keys=True)
        should_publish = force or payload_json != self.last_state_json
        if not should_publish and self.last_state_publish is not None:
            should_publish = (now - self.last_state_publish).to_sec() >= self.state_publish_period
        if not should_publish:
            return
        self.state_pub.publish(payload_json)
        self.last_state_json = payload_json
        self.last_state_publish = now

    def _publish_decision(self, command_event=False, now=None):
        if now is None:
            now = self._now()
        with self.state_lock:
            command = self.latest_command or self.Twist()
            decision = self.logic.decide(
                command,
                tof_seen=self.tof_seen,
                tof_range=self.last_tof_range,
                tof_age=self._age(self.last_tof_time, now),
                scan_seen=self.scan_seen,
                scan_age=self._age(self.last_scan_time, now),
                battery_guard_mode=self.battery_guard_mode,
                battery_percent=self.battery_percent,
                charging=self.charging,
            )
            publish_status = self.command_policy.decide_publish(decision, now.to_sec(), command_event=command_event)
            if publish_status["publish"]:
                output_command = decision["command"]
                if publish_status["publish_stop"]:
                    output_command = self.logic.zero_twist(command)
                self.command_pub.publish(output_command)
            self._publish_state(decision, publish_status, now, force=command_event)

    def log_active(self):
        self.rospy.loginfo(
            "Scout safety filter active: %s -> %s (tof=%s, scan=%s)",
            self.input_topic,
            self.output_topic,
            self.tof_topic,
            self.scan_topic,
        )

    def tick(self, event=None):
        self._publish_decision(command_event=False)

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
    node = ScoutSafetyFilterNode(config_path=args.config, site_path=args.site)
    node.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

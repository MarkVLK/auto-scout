#!/usr/bin/env python3
"""Unit tests for Scout command safety filtering."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scout_safety_filter import ScoutCommandPublishPolicy
from scout_safety_filter import ScoutSafetyLogic


class Vector3:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0


class Twist:
    def __init__(self):
        self.linear = Vector3()
        self.angular = Vector3()


def twist(linear_x=0.2, angular_z=0.1):
    msg = Twist()
    msg.linear.x = linear_x
    msg.angular.z = angular_z
    return msg


class ScoutSafetyLogicTest(unittest.TestCase):
    def make_logic(self, **overrides):
        defaults = {
            "twist_type": Twist,
            "tof_stop_enabled": True,
            "require_tof": False,
            "max_obstacle_distance": 0.3,
            "emergency_stop_distance": 0.15,
            "tof_stale_timeout": 1.0,
            "scan_watchdog_enabled": True,
            "scan_stale_timeout": 1.0,
            "caution_speed": 0.05,
            "mission_start_min_battery_level": 50.0,
        }
        defaults.update(overrides)
        return ScoutSafetyLogic(**defaults)

    def test_clear_tof_passes_planner_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
        )

        self.assertEqual(decision["state"], "clear")
        self.assertFalse(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.2)
        self.assertAlmostEqual(decision["command"].angular.z, 0.1)

    def test_caution_range_clamps_forward_speed(self):
        decision = self.make_logic().decide(
            twist(linear_x=0.2),
            tof_seen=True,
            tof_range=0.25,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
        )

        self.assertEqual(decision["state"], "tof_caution")
        self.assertFalse(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.05)
        self.assertAlmostEqual(decision["command"].angular.z, 0.1)

    def test_emergency_range_outputs_zero_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.1,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
        )

        self.assertEqual(decision["state"], "tof_stop")
        self.assertTrue(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.0)
        self.assertAlmostEqual(decision["command"].angular.z, 0.0)

    def test_stale_scan_outputs_zero_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=1.5,
        )

        self.assertEqual(decision["state"], "scan_stale")
        self.assertTrue(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.0)
        self.assertAlmostEqual(decision["command"].angular.z, 0.0)

    def test_missing_optional_tof_warns_but_does_not_block(self):
        decision = self.make_logic(require_tof=False).decide(
            twist(),
            tof_seen=False,
            tof_range=None,
            tof_age=None,
            scan_seen=True,
            scan_age=0.1,
        )

        self.assertEqual(decision["state"], "tof_unavailable")
        self.assertFalse(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.2)

    def test_missing_required_tof_blocks_motion(self):
        decision = self.make_logic(require_tof=True).decide(
            twist(),
            tof_seen=False,
            tof_range=None,
            tof_age=None,
            scan_seen=True,
            scan_age=0.1,
        )

        self.assertEqual(decision["state"], "tof_unavailable")
        self.assertTrue(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.0)

    def test_battery_guard_map_return_allows_planner_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode="map_return",
        )

        self.assertEqual(decision["state"], "clear")
        self.assertFalse(decision["blocked"])
        self.assertAlmostEqual(decision["command"].linear.x, 0.2)

    def test_battery_guard_return_modes_block_planner_command(self):
        for mode in ["return_required", "vendor_docking", "failed"]:
            decision = self.make_logic().decide(
                twist(),
                tof_seen=True,
                tof_range=0.5,
                tof_age=0.1,
                scan_seen=True,
                scan_age=0.1,
                battery_guard_mode=mode,
            )

            self.assertEqual(decision["state"], "battery_guard_{}".format(mode))
            self.assertTrue(decision["blocked"])
            self.assertAlmostEqual(decision["command"].linear.x, 0.0)
            self.assertAlmostEqual(decision["command"].angular.z, 0.0)

    def test_charging_above_mission_start_threshold_allows_planner_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode="charging",
            battery_percent=100.0,
            charging=True,
        )

        self.assertEqual(decision["state"], "clear")
        self.assertFalse(decision["blocked"])
        self.assertTrue(decision["charging"])
        self.assertAlmostEqual(decision["battery_percent"], 100.0)
        self.assertAlmostEqual(decision["mission_start_min_battery_level"], 50.0)
        self.assertAlmostEqual(decision["command"].linear.x, 0.2)

    def test_charging_below_mission_start_threshold_blocks_planner_command(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode="charging",
            battery_percent=49.0,
            charging=True,
        )

        self.assertEqual(decision["state"], "dock_charge_required")
        self.assertTrue(decision["blocked"])
        self.assertTrue(decision["charging"])
        self.assertAlmostEqual(decision["battery_percent"], 49.0)
        self.assertAlmostEqual(decision["mission_start_min_battery_level"], 50.0)
        self.assertAlmostEqual(decision["command"].linear.x, 0.0)

    def test_charging_with_unknown_battery_does_not_block_by_itself(self):
        decision = self.make_logic().decide(
            twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode="charging",
            battery_percent=None,
            charging=True,
        )

        self.assertEqual(decision["state"], "clear")
        self.assertFalse(decision["blocked"])
        self.assertTrue(decision["charging"])
        self.assertIsNone(decision["battery_percent"])


class ScoutCommandPublishPolicyTest(unittest.TestCase):
    def make_logic(self):
        return ScoutSafetyLogic(twist_type=Twist)

    def make_policy(self):
        return ScoutCommandPublishPolicy(command_stale_timeout=0.5)

    def clear_decision(self, logic, command=None, mode=None):
        return logic.decide(
            command or twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode=mode,
        )

    def stale_scan_decision(self, logic, command=None):
        return logic.decide(
            command or twist(),
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=1.5,
        )

    def test_no_planner_input_does_not_publish_stop_when_scan_unavailable(self):
        logic = self.make_logic()
        policy = self.make_policy()
        decision = logic.decide(twist(), tof_seen=True, tof_range=0.5, tof_age=0.1, scan_seen=False)

        result = policy.decide_publish(decision, now=0.0)

        self.assertEqual(decision["state"], "scan_unavailable")
        self.assertFalse(result["publish"])
        self.assertFalse(result["command_active"])
        self.assertIsNone(result["command_age"])
        self.assertTrue(result["command_suppressed"])

    def test_blocked_active_planner_publishes_one_stop_only(self):
        logic = self.make_logic()
        policy = self.make_policy()
        command = twist()

        policy.note_command(0.0)
        first = policy.decide_publish(self.stale_scan_decision(logic, command), now=0.0, command_event=True)
        second = policy.decide_publish(self.stale_scan_decision(logic, command), now=0.1)
        policy.note_command(0.2)
        third = policy.decide_publish(self.stale_scan_decision(logic, command), now=0.2, command_event=True)

        self.assertTrue(first["publish"])
        self.assertTrue(first["publish_stop"])
        self.assertFalse(second["publish"])
        self.assertTrue(second["command_suppressed"])
        self.assertFalse(third["publish"])
        self.assertTrue(third["command_suppressed"])

    def test_command_stream_expiry_publishes_one_stop_then_stays_quiet(self):
        logic = self.make_logic()
        policy = self.make_policy()
        command = twist()

        policy.note_command(0.0)
        first = policy.decide_publish(self.clear_decision(logic, command), now=0.0, command_event=True)
        stale = policy.decide_publish(self.clear_decision(logic, command), now=0.6)
        repeated = policy.decide_publish(self.clear_decision(logic, command), now=0.7)

        self.assertTrue(first["publish"])
        self.assertFalse(first["publish_stop"])
        self.assertTrue(stale["publish"])
        self.assertTrue(stale["publish_stop"])
        self.assertFalse(stale["command_active"])
        self.assertFalse(repeated["publish"])

    def test_battery_guard_block_modes_do_not_repeat_stop_commands(self):
        logic = self.make_logic()
        for mode in ["vendor_docking", "failed"]:
            policy = self.make_policy()
            command = twist()

            policy.note_command(0.0)
            first = policy.decide_publish(self.clear_decision(logic, command, mode=mode), now=0.0, command_event=True)
            second = policy.decide_publish(self.clear_decision(logic, command, mode=mode), now=0.1)
            policy.note_command(0.2)
            third = policy.decide_publish(self.clear_decision(logic, command, mode=mode), now=0.2, command_event=True)

            self.assertTrue(first["publish"])
            self.assertTrue(first["publish_stop"])
            self.assertFalse(second["publish"])
            self.assertTrue(second["command_suppressed"])
            self.assertFalse(third["publish"])
            self.assertTrue(third["command_suppressed"])

    def test_dock_charge_required_does_not_repeat_stop_commands(self):
        logic = self.make_logic()
        policy = self.make_policy()
        command = twist()
        decision = logic.decide(
            command,
            tof_seen=True,
            tof_range=0.5,
            tof_age=0.1,
            scan_seen=True,
            scan_age=0.1,
            battery_guard_mode="charging",
            battery_percent=49.0,
            charging=True,
        )

        policy.note_command(0.0)
        first = policy.decide_publish(decision, now=0.0, command_event=True)
        second = policy.decide_publish(decision, now=0.1)
        policy.note_command(0.2)
        third = policy.decide_publish(decision, now=0.2, command_event=True)

        self.assertTrue(first["publish"])
        self.assertTrue(first["publish_stop"])
        self.assertFalse(second["publish"])
        self.assertTrue(second["command_suppressed"])
        self.assertFalse(third["publish"])
        self.assertTrue(third["command_suppressed"])

    def test_map_return_continues_to_publish_safe_planner_commands(self):
        logic = self.make_logic()
        policy = self.make_policy()
        command = twist(linear_x=0.2)

        policy.note_command(0.0)
        result = policy.decide_publish(self.clear_decision(logic, command, mode="map_return"), now=0.0, command_event=True)

        self.assertTrue(result["publish"])
        self.assertFalse(result["publish_stop"])
        self.assertTrue(result["command_active"])
        self.assertFalse(result["command_suppressed"])


if __name__ == "__main__":
    unittest.main()

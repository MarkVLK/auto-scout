#!/usr/bin/env python3
"""Unit tests for Scout command safety filtering."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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
        for mode in ["return_required", "vendor_docking", "failed", "charging"]:
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


if __name__ == "__main__":
    unittest.main()

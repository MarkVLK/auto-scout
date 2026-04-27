#!/usr/bin/env python3
"""Unit tests for companion-side battery map-return eligibility."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from battery_map_return_controller import BatteryMapReturnLogic


class BatteryMapReturnLogicTest(unittest.TestCase):
    def make_logic(self, **overrides):
        defaults = {
            "localization_mode": True,
            "dock_waypoint": "charging_station",
            "waypoints": {"charging_station": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}},
            "pose_stale_timeout": 3.0,
        }
        defaults.update(overrides)
        return BatteryMapReturnLogic(**defaults)

    def test_does_not_claim_without_localization_mode(self):
        can_claim, reason = self.make_logic(localization_mode=False).can_claim(True, 10.0, 9.0)

        self.assertFalse(can_claim)
        self.assertEqual(reason, "localization_mode_disabled")

    def test_does_not_claim_without_dock_waypoint(self):
        can_claim, reason = self.make_logic(waypoints={}).can_claim(True, 10.0, 9.0)

        self.assertFalse(can_claim)
        self.assertEqual(reason, "dock_waypoint_missing")

    def test_does_not_claim_without_fresh_pose(self):
        can_claim, reason = self.make_logic().can_claim(True, 10.0, 6.5)

        self.assertFalse(can_claim)
        self.assertEqual(reason, "pose_stale")

    def test_does_not_claim_without_move_base(self):
        can_claim, reason = self.make_logic().can_claim(False, 10.0, 9.0)

        self.assertFalse(can_claim)
        self.assertEqual(reason, "move_base_unavailable")

    def test_claims_when_navigation_stack_is_healthy(self):
        can_claim, reason = self.make_logic().can_claim(True, 10.0, 9.0)

        self.assertTrue(can_claim)
        self.assertEqual(reason, "map_return_ready")


if __name__ == "__main__":
    unittest.main()

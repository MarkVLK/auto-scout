#!/usr/bin/env python3
"""Unit tests for the Scout-local battery docking guard state machine."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scout_battery_dock_guard import ACTION_CALL_VENDOR_DOCK
from scout_battery_dock_guard import MODE_CHARGING
from scout_battery_dock_guard import MODE_FAILED
from scout_battery_dock_guard import MODE_IDLE
from scout_battery_dock_guard import MODE_MAP_RETURN
from scout_battery_dock_guard import MODE_RETURN_REQUIRED
from scout_battery_dock_guard import MODE_VENDOR_DOCKING
from scout_battery_dock_guard import VENDOR_STATUS_FAIL
from scout_battery_dock_guard import VENDOR_STATUS_SUCCESS
from scout_battery_dock_guard import ScoutBatteryDockGuardLogic


class ScoutBatteryDockGuardLogicTest(unittest.TestCase):
    def make_logic(self, **overrides):
        defaults = {
            "min_battery_level": 20.0,
            "critical_battery_level": 10.0,
            "battery_reset_margin": 5.0,
            "map_return_claim_timeout_seconds": 5.0,
            "map_return_timeout_seconds": 20.0,
            "dock_timeout_seconds": 30.0,
            "dock_retry_count": 1,
        }
        defaults.update(overrides)
        return ScoutBatteryDockGuardLogic(**defaults)

    def test_no_action_above_threshold(self):
        logic = self.make_logic()

        actions = logic.handle_battery(50.0, False, 100.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_IDLE)

    def test_trigger_at_threshold(self):
        logic = self.make_logic()

        actions = logic.handle_battery(20.0, False, 100.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_RETURN_REQUIRED)
        self.assertEqual(logic.claim_deadline, 105.0)

    def test_no_trigger_while_charging(self):
        logic = self.make_logic()

        actions = logic.handle_battery(5.0, True, 100.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_CHARGING)
        self.assertEqual(logic.attempt, 0)
        self.assertTrue(logic.state_payload()["active"])

    def test_companion_claim_accepted_only_during_return_required(self):
        logic = self.make_logic()

        self.assertEqual(logic.handle_control({"action": "claim_map_return"}, 100.0), [])
        self.assertEqual(logic.mode, MODE_IDLE)

        logic.handle_battery(20.0, False, 100.0)
        actions = logic.handle_control({"action": "claim_map_return", "reason": "ready"}, 101.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_MAP_RETURN)
        self.assertEqual(logic.map_return_deadline, 121.0)

    def test_no_claim_causes_vendor_fallback(self):
        logic = self.make_logic()
        logic.handle_battery(20.0, False, 100.0)

        actions = logic.tick(105.0)

        self.assertEqual(actions, [ACTION_CALL_VENDOR_DOCK])
        self.assertEqual(logic.mode, MODE_VENDOR_DOCKING)
        self.assertEqual(logic.attempt, 1)

    def test_vendor_success_marks_charging(self):
        logic = self.make_logic()
        logic.handle_battery(20.0, False, 100.0)
        logic.tick(105.0)

        actions = logic.handle_vendor_status(VENDOR_STATUS_SUCCESS, 106.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_CHARGING)
        self.assertIsNone(logic.vendor_deadline)

    def test_vendor_failure_retries_once_then_fails(self):
        logic = self.make_logic(dock_retry_count=1)
        logic.handle_battery(20.0, False, 100.0)
        logic.tick(105.0)

        retry_actions = logic.handle_vendor_status(VENDOR_STATUS_FAIL, 106.0)
        final_actions = logic.handle_vendor_status(VENDOR_STATUS_FAIL, 107.0)

        self.assertEqual(retry_actions, [ACTION_CALL_VENDOR_DOCK])
        self.assertEqual(final_actions, [])
        self.assertEqual(logic.mode, MODE_FAILED)
        self.assertEqual(logic.attempt, 2)

    def test_battery_recovery_does_not_abandon_vendor_docking(self):
        """Percent recovers as load drops near the dock; the dock must continue."""
        logic = self.make_logic()
        logic.handle_battery(20.0, False, 100.0)
        logic.tick(105.0)
        self.assertEqual(logic.mode, MODE_VENDOR_DOCKING)

        actions = logic.handle_battery(28.0, False, 106.0)

        self.assertEqual(actions, [])
        self.assertEqual(logic.mode, MODE_VENDOR_DOCKING)
        self.assertIsNotNone(logic.vendor_deadline)

    def test_battery_recovery_does_not_abandon_map_return(self):
        logic = self.make_logic()
        logic.handle_battery(20.0, False, 100.0)
        logic.handle_control({"action": "claim_map_return"}, 101.0)
        self.assertEqual(logic.mode, MODE_MAP_RETURN)

        logic.handle_battery(30.0, False, 102.0)

        self.assertEqual(logic.mode, MODE_MAP_RETURN)
        self.assertIsNotNone(logic.map_return_deadline)

    def test_battery_recovery_still_resets_from_return_required(self):
        """A recovery before any return has started is a legitimate reset."""
        logic = self.make_logic()
        logic.handle_battery(20.0, False, 100.0)
        self.assertEqual(logic.mode, MODE_RETURN_REQUIRED)

        logic.handle_battery(30.0, False, 101.0)

        self.assertEqual(logic.mode, MODE_IDLE)
        self.assertIsNone(logic.claim_deadline)

    def test_implausible_battery_readings_are_ignored(self):
        """Out-of-range values mean the vendor array layout changed, not a flat battery."""
        logic = self.make_logic()
        logic.handle_battery(60.0, False, 100.0)

        for bad_value in [-1.0, 101.0, 65535.0, float("nan"), float("inf"), "n/a", None]:
            actions = logic.handle_battery(bad_value, False, 101.0)

            self.assertEqual(actions, [], bad_value)
            self.assertEqual(logic.mode, MODE_IDLE, bad_value)
            self.assertEqual(logic.battery_percent, 60.0, bad_value)

    def test_implausible_battery_reading_is_surfaced_in_state(self):
        logic = self.make_logic()
        logic.handle_battery(60.0, False, 100.0)

        logic.handle_battery(65535.0, False, 101.0)
        self.assertEqual(logic.state_payload()["rejected_battery_reading"], 65535.0)

        logic.handle_battery(55.0, False, 102.0)
        self.assertIsNone(logic.state_payload()["rejected_battery_reading"])

    def test_boundary_battery_percentages_are_accepted(self):
        logic = self.make_logic()

        logic.handle_battery(100.0, False, 100.0)
        self.assertEqual(logic.battery_percent, 100.0)

        logic.handle_battery(0.0, False, 101.0)
        self.assertEqual(logic.battery_percent, 0.0)
        self.assertEqual(logic.mode, MODE_VENDOR_DOCKING)

    def test_vendor_timeout_retries_once_then_fails(self):
        logic = self.make_logic(dock_retry_count=1, dock_timeout_seconds=2.0)
        logic.handle_battery(20.0, False, 100.0)
        logic.tick(105.0)

        retry_actions = logic.tick(107.0)
        final_actions = logic.tick(109.0)

        self.assertEqual(retry_actions, [ACTION_CALL_VENDOR_DOCK])
        self.assertEqual(final_actions, [])
        self.assertEqual(logic.mode, MODE_FAILED)
        self.assertEqual(logic.attempt, 2)


if __name__ == "__main__":
    unittest.main()

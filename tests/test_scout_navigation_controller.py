#!/usr/bin/env python3
"""Unit tests for companion mission start gating."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scout_navigation_controller import BATTERY_TOO_LOW_REASON
from scout_navigation_controller import CompanionMissionController
from scout_navigation_controller import evaluate_dock_departure_gate


class FakeStatusPublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeRospy:
    def __init__(self):
        self.logs = []

    def loginfo(self, message):
        self.logs.append(message)


class FakeResponse:
    status_code = 202

    def raise_for_status(self):
        return None


class DockDepartureGateTest(unittest.TestCase):
    def test_docked_at_threshold_allows_mission_start(self):
        gate = evaluate_dock_departure_gate(
            {"mode": "charging", "charging": True, "battery_percent": 50.0},
            50.0,
        )

        self.assertTrue(gate["ok"])
        self.assertEqual(gate["reason"], "dock_departure_allowed")

    def test_docked_below_threshold_refuses_mission_start(self):
        gate = evaluate_dock_departure_gate(
            {"mode": "charging", "charging": True, "battery_percent": 49.9},
            50.0,
        )

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["reason"], BATTERY_TOO_LOW_REASON)
        self.assertAlmostEqual(gate["battery_percent"], 49.9)
        self.assertAlmostEqual(gate["mission_start_min_battery_level"], 50.0)

    def test_undocked_low_battery_is_left_to_return_guard(self):
        gate = evaluate_dock_departure_gate(
            {"mode": "return_required", "charging": False, "battery_percent": 10.0},
            50.0,
        )

        self.assertTrue(gate["ok"])
        self.assertFalse(gate["charging"])


class MissionStartRefusalTest(unittest.TestCase):
    def make_controller(self, temp_dir):
        controller = CompanionMissionController.__new__(CompanionMissionController)
        controller.artifact_dir = temp_dir
        controller.log_path = str(Path(temp_dir) / "mission.log")
        controller.mission = {"name": "smoke_loop"}
        controller.site_config = {
            "roles": {
                "companion": {
                    "notifications": {
                        "webhook_url": "https://notify.example.test/auto-scout",
                    },
                },
            },
        }
        controller.config = {"storage": {}}
        controller.rospy = FakeRospy()
        controller.status_pub = FakeStatusPublisher()
        return controller

    def test_refusal_writes_status_and_posts_notification(self):
        gate = evaluate_dock_departure_gate(
            {"mode": "charging", "charging": True, "battery_percent": 49.9},
            50.0,
        )
        posts = []

        def fake_post(url, json=None, timeout=None):
            posts.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            with patch("scout_navigation_controller.requests.post", side_effect=fake_post):
                result = controller.refuse_mission_start(gate)
            result_path = Path(temp_dir) / "mission-result.json"
            written = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["reason"], BATTERY_TOO_LOW_REASON)
        self.assertAlmostEqual(result["battery_percent"], 49.9)
        self.assertTrue(result["notification"]["sent"])
        self.assertEqual(posts[0]["url"], "https://notify.example.test/auto-scout")
        self.assertEqual(posts[0]["json"]["reason"], BATTERY_TOO_LOW_REASON)
        self.assertAlmostEqual(posts[0]["json"]["battery_percent"], 49.9)
        self.assertEqual(written["reason"], BATTERY_TOO_LOW_REASON)
        status_payload = json.loads(controller.status_pub.messages[-1])
        self.assertEqual(status_payload["reason"], BATTERY_TOO_LOW_REASON)


if __name__ == "__main__":
    unittest.main()

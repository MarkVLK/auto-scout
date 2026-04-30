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
from scout_navigation_controller import CAMERA_FRAME_UNAVAILABLE_REASON
from scout_navigation_controller import CompanionMissionController
from scout_navigation_controller import NAV_STACK_DISABLED_REASON
from scout_navigation_controller import NAVIGATION_TF_UNAVAILABLE_REASON
from scout_navigation_controller import REQUIRED_NAVIGATION_TF_EDGES
from scout_navigation_controller import evaluate_dock_departure_gate


class FakeStatusPublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeRospy:
    def __init__(self):
        self.logs = []
        self._shutdown = False

    class Time:
        @staticmethod
        def now():
            return FakeRosTime(0.0)

    def loginfo(self, message):
        self.logs.append(message)

    def is_shutdown(self):
        return self._shutdown

    def sleep(self, seconds):
        return None


class FakeRosTime:
    def __init__(self, value):
        self.value = value

    def __sub__(self, other):
        return FakeRosDuration(self.value - other.value)


class FakeRosDuration:
    def __init__(self, value):
        self.value = value

    def to_sec(self):
        return self.value


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
        controller.scan_seen = False
        controller.tf_edges = set()
        controller.TFMessage = object
        controller.camera_topic = "/camera/image_raw/compressed"
        controller.latest_image = None
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
        self.assertIn("text", posts[0]["json"])
        self.assertIn("Auto-Scout mission blocked", posts[0]["json"]["text"])
        self.assertIn("blocks", posts[0]["json"])
        self.assertIn(BATTERY_TOO_LOW_REASON, str(posts[0]["json"]["blocks"]))
        self.assertIn("49.9%", str(posts[0]["json"]["blocks"]))
        self.assertNotIn("https://notify.example.test/auto-scout", "\n".join(controller.rospy.logs))
        self.assertEqual(written["reason"], BATTERY_TOO_LOW_REASON)
        status_payload = json.loads(controller.status_pub.messages[-1])
        self.assertEqual(status_payload["reason"], BATTERY_TOO_LOW_REASON)

    def test_navigation_preflight_allows_when_scan_and_required_tf_are_seen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.scan_seen = True
            controller.tf_edges = set(REQUIRED_NAVIGATION_TF_EDGES)

            result = controller.evaluate_navigation_preflight()

        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "navigation_inputs_available")
        self.assertEqual(result["missing_tf_edges"], [])

    def test_navigation_preflight_refuses_missing_tf_before_navigation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.site_config["roles"]["companion"]["notifications"]["webhook_url"] = ""
            controller.wait_for_battery_guard_state = lambda: {
                "mode": "charging",
                "charging": True,
                "battery_percent": 100.0,
            }
            controller.mission_start_min_battery_level = lambda: 50.0
            controller.scan_seen = True
            controller.tf_edges = {("odom", "base_link")}
            controller.evaluate_navigation_preflight = lambda: controller.navigation_input_state()
            controller.wait_for_pose = lambda: self.fail("wait_for_pose should not run after TF preflight refusal")
            controller.wait_for_move_base = lambda: self.fail("wait_for_move_base should not run after TF preflight refusal")

            with patch.dict("os.environ", {"AUTO_SCOUT_ENABLE_NAV_STACK": "true"}):
                result = controller.run_smoke_loop()

        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["reason"], NAVIGATION_TF_UNAVAILABLE_REASON)
        self.assertEqual(result["missing_tf_edges"], [{"parent": "base_link", "child": "base_laser"}])

    def test_mission_proceeds_when_navigation_preflight_is_clear(self):
        navigated = []
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.wait_for_battery_guard_state = lambda: {
                "mode": "charging",
                "charging": True,
                "battery_percent": 100.0,
            }
            controller.mission_start_min_battery_level = lambda: 50.0
            controller.scan_seen = True
            controller.tf_edges = set(REQUIRED_NAVIGATION_TF_EDGES)
            controller.mission = {
                "name": "smoke_loop",
                "route": {"loop_waypoints": ["one"]},
            }
            controller.wait_for_pose = lambda: None
            controller.wait_for_move_base = lambda: None
            controller.navigate_to_waypoint = navigated.append
            controller.request_return = lambda: {"mode": "vendor_dock_requested"}
            controller.capture_photo = lambda: "/tmp/photo.jpg"
            controller.send_notification = lambda photo, return_result: {"sent": False, "reason": "disabled"}
            controller.latest_pose = {"source": "odom"}

            with patch.dict("os.environ", {"AUTO_SCOUT_ENABLE_NAV_STACK": "true"}):
                result = controller.run_smoke_loop()

        self.assertTrue(result["ok"])
        self.assertEqual(navigated, ["one"])

    def test_still_photo_mission_refuses_before_navigation_when_no_camera_frame(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.site_config["roles"]["companion"]["notifications"]["webhook_url"] = ""
            controller.wait_for_battery_guard_state = lambda: {
                "mode": "charging",
                "charging": True,
                "battery_percent": 100.0,
            }
            controller.mission_start_min_battery_level = lambda: 50.0
            controller.scan_seen = True
            controller.tf_edges = set(REQUIRED_NAVIGATION_TF_EDGES)
            controller.mission = {
                "name": "smoke_loop",
                "capture": {"action": "still_photo"},
                "route": {"loop_waypoints": ["one"]},
            }
            controller.evaluate_camera_preflight = lambda: controller.camera_input_state()
            controller.wait_for_pose = lambda: self.fail("wait_for_pose should not run after camera preflight refusal")
            controller.wait_for_move_base = lambda: self.fail("wait_for_move_base should not run after camera preflight refusal")

            with patch.dict("os.environ", {"AUTO_SCOUT_ENABLE_NAV_STACK": "true"}):
                result = controller.run_smoke_loop()

        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["reason"], CAMERA_FRAME_UNAVAILABLE_REASON)
        self.assertEqual(result["camera_topic"], "/camera/image_raw/compressed")

    def test_still_photo_mission_proceeds_when_camera_frame_is_available(self):
        navigated = []
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.wait_for_battery_guard_state = lambda: {
                "mode": "charging",
                "charging": True,
                "battery_percent": 100.0,
            }
            controller.mission_start_min_battery_level = lambda: 50.0
            controller.scan_seen = True
            controller.tf_edges = set(REQUIRED_NAVIGATION_TF_EDGES)
            controller.latest_image = object()
            controller.mission = {
                "name": "smoke_loop",
                "capture": {"action": "still_photo"},
                "route": {"loop_waypoints": ["one"]},
            }
            controller.wait_for_pose = lambda: None
            controller.wait_for_move_base = lambda: None
            controller.navigate_to_waypoint = navigated.append
            controller.request_return = lambda: {"mode": "vendor_dock_requested"}
            controller.capture_photo = lambda: "/tmp/photo.jpg"
            controller.send_notification = lambda photo, return_result: {"sent": False, "reason": "disabled"}
            controller.latest_pose = {"source": "odom"}

            with patch.dict("os.environ", {"AUTO_SCOUT_ENABLE_NAV_STACK": "true"}):
                result = controller.run_smoke_loop()

        self.assertTrue(result["ok"])
        self.assertEqual(navigated, ["one"])

    def test_mission_refuses_before_battery_check_when_nav_stack_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.wait_for_battery_guard_state = lambda: self.fail("battery check should not run when nav is disabled")
            controller.evaluate_navigation_preflight = lambda: self.fail("navigation preflight should not run when nav is disabled")
            controller.evaluate_camera_preflight = lambda: self.fail("camera preflight should not run when nav is disabled")

            with patch.dict("os.environ", {"AUTO_SCOUT_ENABLE_NAV_STACK": "false"}):
                result = controller.run_smoke_loop()

        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["reason"], NAV_STACK_DISABLED_REASON)

    def test_notification_url_ignores_legacy_storage_webhook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            controller.site_config["roles"]["companion"]["notifications"]["webhook_url"] = ""
            controller.config = {"storage": {"webhook_url": "https://notify.example.test/legacy"}}

            self.assertEqual(controller.notification_webhook_url(), "")

    def test_preflight_notification_error_redacts_slack_webhook_path(self):
        def fake_post(url, json=None, timeout=None):
            raise RuntimeError("failed with url: /services/T000/B000/SECRET")

        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self.make_controller(temp_dir)
            with patch("scout_navigation_controller.requests.post", side_effect=fake_post):
                result = controller.send_preflight_notification(
                    {
                        "mission": "smoke_loop",
                        "reason": BATTERY_TOO_LOW_REASON,
                        "timestamp": "2026-04-29T12:00:00Z",
                    }
                )

        self.assertFalse(result["sent"])
        self.assertNotIn("SECRET", result["error"])


if __name__ == "__main__":
    unittest.main()

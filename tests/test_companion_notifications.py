#!/usr/bin/env python3
"""Tests for companion Slack notification payload helpers."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.notifications import build_mission_success_payload
from auto_scout.notifications import build_preflight_refusal_payload
from auto_scout.notifications import build_test_notification_payload
from auto_scout.notifications import companion_notification_webhook_url


class CompanionNotificationPayloadTest(unittest.TestCase):
    def test_success_payload_is_slack_compatible(self):
        payload = build_mission_success_payload(
            "smoke_loop",
            "/srv/auto-scout/artifacts/run-001",
            "/srv/auto-scout/media/proof.jpg",
            {"mode": "fallback_waypoint", "waypoint": "charging_station"},
            "2026-04-29T12:00:00Z",
        )

        self.assertIn("text", payload)
        self.assertIn("Auto-Scout mission passed", payload["text"])
        self.assertIn("blocks", payload)
        rendered = str(payload["blocks"])
        self.assertIn("smoke_loop", rendered)
        self.assertIn("charging_station", rendered)

    def test_preflight_refusal_payload_is_slack_compatible(self):
        payload = build_preflight_refusal_payload(
            {
                "mission": "smoke_loop",
                "reason": "battery_too_low_to_leave_dock",
                "battery_percent": 49.9,
                "charging": True,
                "battery_guard_mode": "charging",
                "mission_start_min_battery_level": 50.0,
                "artifact_dir": "/srv/auto-scout/artifacts/run-002",
                "timestamp": "2026-04-29T12:00:00Z",
            }
        )

        self.assertIn("text", payload)
        self.assertIn("Auto-Scout mission blocked", payload["text"])
        self.assertIn("blocks", payload)
        rendered = str(payload["blocks"])
        self.assertIn("battery_too_low_to_leave_dock", rendered)
        self.assertIn("49.9%", rendered)

    def test_test_payload_uses_required_text(self):
        payload = build_test_notification_payload("hello scout")

        self.assertEqual(payload["text"], "hello scout")
        self.assertIn("blocks", payload)

    def test_companion_webhook_url_does_not_fall_back_to_legacy_storage(self):
        site_config = {
            "roles": {
                "companion": {
                    "notifications": {
                        "webhook_url": "",
                    },
                },
            },
        }
        legacy_project_config = {"storage": {"webhook_url": "https://notify.example.test/legacy"}}

        self.assertEqual(companion_notification_webhook_url(site_config), "")
        self.assertEqual(legacy_project_config["storage"]["webhook_url"], "https://notify.example.test/legacy")


if __name__ == "__main__":
    unittest.main()

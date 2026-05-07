#!/usr/bin/env python3
"""Tests for critical Scout/Pi resource alert evaluation."""

import tempfile
import time
import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.notifications import build_resource_alert_payload
from auto_scout.resource_alerts import choose_alert_delivery
from auto_scout.resource_alerts import parse_companion_health
from auto_scout.resource_alerts import parse_scout_health
from auto_scout.resource_alerts import scout_ssh_config_for_resource_check
from auto_scout.resource_alerts import summarize_resource_health


class ResourceAlertTest(unittest.TestCase):
    def test_local_companion_resource_check_targets_scout_alias(self):
        scout_ssh = {
            "host": "192.168.0.199",
            "user": "linaro",
            "port": 22,
            "host_key_alias": "moorebot-scout.local",
        }

        selected = scout_ssh_config_for_resource_check(scout_ssh, local_companion=True)

        self.assertEqual(selected["host"], "moorebot-scout.local")
        self.assertEqual(scout_ssh["host"], "192.168.0.199")

    def test_remote_resource_check_keeps_configured_scout_host(self):
        scout_ssh = {
            "host": "192.168.0.199",
            "user": "linaro",
            "port": 22,
            "host_key_alias": "moorebot-scout.local",
        }

        selected = scout_ssh_config_for_resource_check(scout_ssh, local_companion=False)

        self.assertEqual(selected["host"], "192.168.0.199")

    def test_scout_health_flags_critical_thresholds(self):
        output = """__UNITS__
auto-scout-scout-runtime.service active
auto-scout-scout-resource-metrics.timer inactive
userdata-auto\\x2dscout-auto\\x2dscout.swap.swap active
__FREE__
              total        used        free      shared  buff/cache   available
Mem:            955         820          20           3         115         120
Swap:           511         247         263
__SWAPS__
Filename                                Type            Size    Used    Priority
__VMSTAT__
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 1  0 253756  44104  80340 197616   10    2     0    48 11053 11136 29 15 55  0  0
 1  0 253756  44104  80340 197616  300  512     0    48 11053 11136 29 15 55  0  0
__DF__
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/root      2457600 2257600    200000      92% /
__PS__
  PID COMMAND         %CPU   RSS COMMAND
 7071 python2         65.1 92160 python2 /userdata/catkin_ws/src/auto-scout/src/scout_imu_bridge.py
__OOM__
kernel: Killed process 7071 (python2)
"""
        report = parse_scout_health(output)
        alert_ids = {alert["id"] for alert in report["alerts"]}

        self.assertFalse(report["ok"])
        self.assertIn("scout_unit_auto-scout-scout-resource-metrics.timer", alert_ids)
        self.assertIn("scout_swap_missing", alert_ids)
        self.assertIn("scout_low_memory", alert_ids)
        self.assertIn("scout_swap_io", alert_ids)
        self.assertIn("scout_root_disk_low", alert_ids)
        self.assertIn("scout_oom", alert_ids)
        self.assertIn("scout_process_cpu_7071", alert_ids)
        self.assertIn("scout_process_rss_7071", alert_ids)

    def test_scout_health_ignores_boot_average_swap_io(self):
        output = """__UNITS__
auto-scout-scout-runtime.service active
auto-scout-scout-resource-metrics.timer active
userdata-auto\\x2dscout-auto\\x2dscout.swap.swap active
__FREE__
              total        used        free      shared  buff/cache   available
Mem:            955         300         300           3         300         450
Swap:           511           5         506
__SWAPS__
Filename                                Type            Size    Used    Priority
/userdata/auto-scout/auto-scout.swap    file            523840  5120    -1
__VMSTAT__
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 1  0   5120 300000  80340 197616    1    5     0    48 11053 11136 29 15 55  0  0
 1  0   5120 300000  80340 197616    0    0     0     0 11053 11136 29 15 55  0  0
 1  0   5120 300000  80340 197616    0    0     0     0 11053 11136 29 15 55  0  0
__DF__
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/root      2457600 1800000    500000      79% /
__PS__
  PID COMMAND         %CPU   RSS COMMAND
 7071 python2         40.1 56320 python2 /userdata/catkin_ws/src/auto-scout/src/scout_core_runtime.py
__OOM__
"""
        report = parse_scout_health(output)
        alert_ids = {alert["id"] for alert in report["alerts"]}

        self.assertTrue(report["ok"], msg=report["alerts"])
        self.assertNotIn("scout_swap_io", alert_ids)

    def test_companion_health_flags_container_down_and_low_resources(self):
        output = """__FAILED_UNITS__
bad.service loaded failed failed bad service
__FREE__
              total        used        free      shared  buff/cache   available
Mem:           7933        7300         100           3         533         512
Swap:              0           0           0
__DF__
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/root     60000000 59000000   4000000      94% /
__DOCKER__
false /auto-scout-melodic
__DOCKER_STATS__
__OOM__
"""
        report = parse_companion_health(output)
        alert_ids = {alert["id"] for alert in report["alerts"]}

        self.assertFalse(report["ok"])
        self.assertIn("pi_failed_units", alert_ids)
        self.assertIn("pi_low_memory", alert_ids)
        self.assertIn("pi_root_disk_low", alert_ids)
        self.assertIn("pi_container_down", alert_ids)

    def test_alert_cooldown_and_recovery(self):
        report = summarize_resource_health(
            {
                "scout": {"ok": False, "alerts": [{"id": "scout_low_memory", "summary": "low", "detail": "low"}]},
                "companion": {"ok": True, "alerts": []},
            },
            timestamp="2026-05-06T00:00:00Z",
        )
        ok_report = summarize_resource_health(
            {
                "scout": {"ok": True, "alerts": []},
                "companion": {"ok": True, "alerts": []},
            },
            timestamp="2026-05-06T00:01:00Z",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            first = choose_alert_delivery(report, state_dir=temp_dir, cooldown_seconds=3600)
            second = choose_alert_delivery(report, state_dir=temp_dir, cooldown_seconds=3600)
            recovery = choose_alert_delivery(ok_report, state_dir=temp_dir, cooldown_seconds=3600)

        self.assertTrue(first.should_send)
        self.assertEqual(first.reason, "new_alert")
        self.assertFalse(second.should_send)
        self.assertEqual(second.reason, "cooldown_suppressed")
        self.assertTrue(recovery.should_send)
        self.assertEqual(recovery.reason, "recovered")

    def test_resource_alert_payload_is_slack_compatible(self):
        report = {
            "status": "critical",
            "timestamp": "2026-05-06T00:00:00Z",
            "alerts": [{"summary": "Scout swap missing", "detail": "/proc/swaps is empty"}],
        }
        payload = build_resource_alert_payload(report)

        self.assertEqual(payload["text"], "Auto-Scout resource alert: critical")
        self.assertIn("blocks", payload)
        self.assertIn("Scout swap missing", str(payload["blocks"]))


if __name__ == "__main__":
    raise SystemExit(unittest.main())

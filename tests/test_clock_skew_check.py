#!/usr/bin/env python3
"""Unit tests for the Scout/companion clock skew validator check."""

import sys
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
for path in [REPO_ROOT, SRC_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_scout_compatibility as validator


def site_config():
    return {
        "roles": {
            "scout": {
                "hostname": "moorebot-scout",
                "ssh": {"host": "192.0.2.10", "user": "linaro", "port": 22},
                "ros": {"advertise_host": "192.0.2.10"},
            },
            "companion": {
                "hostname": "auto-scout-pi5",
                "ssh": {"host": "192.0.2.20", "user": "ubuntu", "port": 22},
                "ros": {"advertise_host": "192.0.2.20"},
            },
        }
    }


class FakeResult:
    def __init__(self, ok=True, stdout="", stderr=""):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr


class FakeExecutor:
    """Returns a clock offset by a controlled amount from the local clock."""

    def __init__(self, offset_seconds=0.0, ok=True, sync_text="NTPSynchronized=yes", delay=0.0):
        self.offset_seconds = offset_seconds
        self.ok = ok
        self.sync_text = sync_text
        self.delay = delay

    def run(self, command, check=False):
        if self.delay:
            time.sleep(self.delay)
        if not self.ok:
            return FakeResult(ok=False, stderr="ssh: connect failed")
        payload = "__EPOCH__\n{:.6f}\n__SYNC__\n{}\n".format(
            time.time() + self.offset_seconds,
            self.sync_text,
        )
        return FakeResult(stdout=payload)


def run_check(executor, effective_role="system", live_probe_enabled=True):
    report = validator.ReportBuilder("runtime", "likely_companion", effective_role)
    original = validator.ProbeExecutor
    original_local = validator._role_matches_local_host
    try:
        validator.ProbeExecutor = lambda *args, **kwargs: executor
        validator._role_matches_local_host = lambda role_settings: False
        validator._add_clock_skew_check(report, site_config(), effective_role, live_probe_enabled)
    finally:
        validator.ProbeExecutor = original
        validator._role_matches_local_host = original_local
    return {item["name"]: item for item in report.build()["checks"]}["runtime.clock_skew"]


class ClockSkewCheckTest(unittest.TestCase):
    def test_synchronized_clocks_pass(self):
        check = run_check(FakeExecutor(offset_seconds=0.0))

        self.assertEqual(check["status"], "pass")
        self.assertLess(abs(check["evidence"]["skew_seconds"]), validator.CLOCK_SKEW_WARN_SECONDS)

    def test_moderate_drift_warns(self):
        check = run_check(FakeExecutor(offset_seconds=0.5))

        self.assertEqual(check["status"], "warn")
        self.assertIn("chrony", " ".join(check["details"]))

    def test_large_drift_fails(self):
        check = run_check(FakeExecutor(offset_seconds=30.0))

        self.assertEqual(check["status"], "fail")
        self.assertGreater(check["evidence"]["skew_seconds"], validator.CLOCK_SKEW_FAIL_SECONDS)

    def test_negative_drift_is_measured_by_magnitude(self):
        """A Scout running behind is just as broken as one running ahead."""
        check = run_check(FakeExecutor(offset_seconds=-30.0))

        self.assertEqual(check["status"], "fail")
        self.assertLess(check["evidence"]["skew_seconds"], 0)

    def test_unreachable_scout_warns_rather_than_fails(self):
        check = run_check(FakeExecutor(ok=False))

        self.assertEqual(check["status"], "warn")

    def test_disabled_probe_skips(self):
        check = run_check(FakeExecutor(), live_probe_enabled=False)

        self.assertEqual(check["status"], "skip")

    def test_companion_only_role_skips(self):
        check = run_check(FakeExecutor(), effective_role="companion")

        self.assertEqual(check["status"], "skip")

    def test_time_sync_state_is_reported_as_evidence(self):
        check = run_check(FakeExecutor(sync_text="NTPSynchronized=no"))

        self.assertIn("NTPSynchronized=no", check["evidence"]["scout_time_sync"])

    def test_round_trip_latency_is_reported_and_cancelled(self):
        """Transport latency must not be mistaken for clock drift."""
        check = run_check(FakeExecutor(offset_seconds=0.0, delay=0.2))

        self.assertEqual(check["status"], "pass")
        self.assertGreater(check["evidence"]["measurement_precision_seconds"], 0.0)

    def test_parse_clock_probe_handles_missing_sections(self):
        epoch, sync = validator._parse_clock_probe("__EPOCH__\n\n__SYNC__\n")
        self.assertIsNone(epoch)
        self.assertEqual(sync, "")

        epoch, sync = validator._parse_clock_probe("__EPOCH__\nnot-a-number\n1700000000.5\n__SYNC__\nok\n")
        self.assertAlmostEqual(epoch, 1700000000.5, places=3)
        self.assertEqual(sync, "ok")


if __name__ == "__main__":
    unittest.main()

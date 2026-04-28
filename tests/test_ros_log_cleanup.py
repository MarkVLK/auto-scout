#!/usr/bin/env python3
"""Unit tests for ROS log retention cleanup."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cleanup_ros_logs


def write_file(path, size=16):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def touch_tree(path, age_days):
    timestamp = time.time() - (age_days * 24 * 60 * 60)
    for root, dirs, files in os.walk(str(path), topdown=False):
        for name in files:
            os.utime(os.path.join(root, name), (timestamp, timestamp))
        for name in dirs:
            os.utime(os.path.join(root, name), (timestamp, timestamp))
    os.utime(str(path), (timestamp, timestamp))


class RosLogCleanupTest(unittest.TestCase):
    def test_preserves_logs_within_age_and_size_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ros-logs"
            write_file(root / "run-current" / "node.log", size=32)

            actions = cleanup_ros_logs.cleanup_path(str(root), max_age_days=7, max_bytes=1024 * 1024)

            self.assertTrue((root / "run-current" / "node.log").is_file())
            self.assertTrue(any(action.startswith("usage ") for action in actions))

    def test_removes_logs_older_than_age_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ros-logs"
            old_run = root / "run-old"
            fresh_run = root / "run-fresh"
            write_file(old_run / "node.log", size=32)
            write_file(fresh_run / "node.log", size=32)
            touch_tree(old_run, age_days=9)

            actions = cleanup_ros_logs.cleanup_path(str(root), max_age_days=7, max_bytes=1024 * 1024)

            self.assertFalse(old_run.exists())
            self.assertTrue(fresh_run.exists())
            self.assertTrue(any("run-old" in action for action in actions))

    def test_prunes_oldest_entries_until_under_size_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ros-logs"
            oldest = root / "run-001"
            newer = root / "run-002"
            newest = root / "run-003"
            write_file(oldest / "node.log", size=2048)
            write_file(newer / "node.log", size=2048)
            write_file(newest / "node.log", size=2048)
            touch_tree(oldest, age_days=3)
            touch_tree(newer, age_days=2)
            touch_tree(newest, age_days=1)

            cleanup_ros_logs.cleanup_path(str(root), max_age_days=7, max_bytes=4096)

            self.assertFalse(oldest.exists())
            self.assertTrue(newest.exists())

    def test_dry_run_reports_removals_without_deleting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ros-logs"
            old_run = root / "run-old"
            write_file(old_run / "node.log", size=32)
            touch_tree(old_run, age_days=9)

            actions = cleanup_ros_logs.cleanup_path(str(root), max_age_days=7, max_bytes=1024, dry_run=True)

            self.assertTrue(old_run.exists())
            self.assertTrue(any(action.startswith("remove ") for action in actions))


if __name__ == "__main__":
    unittest.main()

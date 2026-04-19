#!/usr/bin/env python3
"""Regression tests for the clean-slate validation and CLI entrypoints."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "check_scout_compatibility.py"
CLI = REPO_ROOT / "auto-scout"
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.yaml_loader import load_yaml


def run_validator(*args):
    """Run the canonical validator and return the completed process."""
    return subprocess.run(
        [sys.executable, str(VALIDATOR)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def run_cli(*args):
    """Run the headless CLI and return the completed process."""
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def run_cli_with_input(*args, input_text=""):
    """Run the CLI with interactive stdin content."""
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True,
        text=True,
        input=input_text,
        cwd=str(REPO_ROOT),
    )


def parse_json_output(stdout):
    """Return the final JSON object emitted by a CLI command."""
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        candidate = stdout[index:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON object found in stdout: {}".format(stdout))


class ValidationCliTest(unittest.TestCase):
    """Validate the canonical validation and CLI entry points."""

    def test_repo_mode_json_contract(self):
        result = run_validator("--mode", "repo", "--json")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        report = json.loads(result.stdout)

        expected_checks = {
            "repo.readme_contract",
            "repo.inventory_contract",
            "repo.mission_contract",
            "repo.launch_contract",
            "repo.service_contract",
            "repo.companion_container_contract",
            "repo.cli_contract",
            "repo.legacy_quarantine_contract",
            "repo.code_contract",
        }

        observed_checks = {item["name"] for item in report["checks"]}
        self.assertEqual(report["mode"], "repo")
        self.assertTrue(report["summary"]["ok"])
        self.assertTrue(expected_checks.issubset(observed_checks))

    def test_repo_mode_can_write_json_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "validation-report.json"
            result = run_validator("--mode", "repo", "--json-out", str(report_path))
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["mode"], "repo")
        self.assertTrue(report["summary"]["ok"])

    def test_help_lists_supported_modes_and_roles(self):
        result = run_validator("--help")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("--mode", result.stdout)
        self.assertIn("--role", result.stdout)
        self.assertIn("repo", result.stdout)
        self.assertIn("runtime", result.stdout)
        self.assertIn("all", result.stdout)

    def test_cli_configure_companion_non_interactive_writes_site(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            result = run_cli(
                "--site",
                str(site_path),
                "configure",
                "companion",
                "--non-interactive",
                "--ssh-host",
                "pi5.local",
                "--ssh-user",
                "automark",
                "--workspace-dir",
                "/home/automark/auto-scout",
                "--service-user",
                "automark",
                "--service-group",
                "automark",
                "--storage-root",
                "/mnt/auto-scout",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = parse_json_output(result.stdout)
            site_config = load_yaml(site_path)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["role"], "companion")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["user"], "automark")
        self.assertEqual(site_config["roles"]["companion"]["workspace_dir"], "/home/automark/auto-scout")
        self.assertEqual(site_config["roles"]["companion"]["storage"]["maps_dir"], "/mnt/auto-scout/maps")

    def test_cli_configure_companion_prompt_accepts_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            result = run_cli_with_input(
                "--site",
                str(site_path),
                "configure",
                "companion",
                "--prompt",
                input_text="\nprompted-pi.local\nautomark\n2200\n/home/automark/auto-scout\nautomark\nautomark\n/var/lib/auto-scout\n",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = parse_json_output(result.stdout)
            site_config = load_yaml(site_path)

        self.assertTrue(payload["prompted"])
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["host"], "prompted-pi.local")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["user"], "automark")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["port"], 2200)
        self.assertEqual(site_config["roles"]["companion"]["storage"]["events_dir"], "/var/lib/auto-scout/events")

    def test_runtime_mode_reports_pose_gate_failure_on_default_site(self):
        result = run_validator("--mode", "runtime", "--role", "system", "--json")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        report = json.loads(result.stdout)
        pose_gate = next(item for item in report["checks"] if item["name"] == "runtime.pose_gate")

        self.assertEqual(pose_gate["status"], "fail")
        self.assertIn("Pose remains", pose_gate["summary"])

    def test_cli_deploy_scout_dry_run(self):
        result = run_cli("deploy", "scout", "--dry-run")

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["role"], "scout")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["service"], "auto-scout-scout-runtime.service")

    def test_cli_smoke_loop_dry_run_fails_fast_on_unverified_site(self):
        result = run_cli("run", "smoke-loop", "--dry-run")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], "preflight")
        self.assertTrue(any("pose" in issue for issue in payload["issues"]))
        self.assertTrue(any("notify" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()

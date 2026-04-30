#!/usr/bin/env python3
"""Regression tests for the clean-slate validation and CLI entrypoints."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "check_scout_compatibility.py"
CLI = REPO_ROOT / "auto-scout"
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import check_scout_compatibility as validator
from auto_scout import cli
from auto_scout import mission_runner
from check_scout_compatibility import find_local_markdown_link_targets
from auto_scout.deploy import _render_companion_service
from auto_scout.deploy import _render_ros_log_cleanup_service
from auto_scout.deploy import _render_ros_log_cleanup_timer
from auto_scout.deploy import _render_scout_service
from auto_scout.deploy import _copy_site_inventory_to_remote
from auto_scout.mission_config import load_mission_config
from auto_scout.mission_runner import evaluate_smoke_loop_gate
from auto_scout.mission_runner import _build_smoke_loop_remote_command
from auto_scout.redaction import REDACTED_VALUE
from auto_scout.redaction import redact_sensitive
from auto_scout.site_config import default_site_config
from auto_scout.yaml_loader import load_yaml
from auto_scout.yaml_loader import write_yaml


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
            "repo.docs_link_contract",
            "repo.inventory_contract",
            "repo.mission_contract",
            "repo.launch_contract",
            "repo.service_contract",
            "repo.companion_container_contract",
            "repo.deploy_contract",
            "repo.build_dependency_contract",
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
                "--skip-connectivity-check",
                "--ssh-host",
                "pi5.example.test",
                "--ssh-user",
                "automark",
                "--workspace-dir",
                "/home/automark/auto-scout",
                "--ros-master-uri",
                "http://moorebot-scout.local:11311",
                "--advertise-host",
                "auto-scout-pi5.local",
                "--service-user",
                "automark",
                "--service-group",
                "automark",
                "--storage-root",
                "/mnt/auto-scout",
                "--enable-notify",
                "--notify-webhook-url",
                "https://notify.example.test/auto-scout",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = parse_json_output(result.stdout)
            site_config = load_yaml(site_path)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["role"], "companion")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["user"], "automark")
        self.assertEqual(site_config["roles"]["companion"]["workspace_dir"], "/home/automark/auto-scout")
        self.assertEqual(site_config["roles"]["companion"]["ros"]["master_uri"], "http://moorebot-scout.local:11311")
        self.assertEqual(site_config["roles"]["companion"]["ros"]["advertise_host"], "auto-scout-pi5.local")
        self.assertEqual(site_config["roles"]["companion"]["storage"]["maps_dir"], "/mnt/auto-scout/maps")
        self.assertTrue(site_config["roles"]["companion"]["capabilities"]["notify"])
        self.assertEqual(
            site_config["roles"]["companion"]["notifications"]["webhook_url"],
            "https://notify.example.test/auto-scout",
        )

    def test_cli_configure_redacts_webhook_from_stdout_and_artifact(self):
        artifact_runs = []

        class FakeArtifactRun:
            def __init__(self, name):
                self.name = name
                self.json = {}
                artifact_runs.append(self)

            def write_json(self, name, payload):
                self.json[name] = payload

            def write_text(self, name, content):
                pass

            def log(self, message):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            stdout = io.StringIO()
            secret = "https://notify.example.test/auto-scout"
            with patch.object(cli, "ArtifactRun", FakeArtifactRun):
                with redirect_stdout(stdout):
                    return_code = cli.main(
                        [
                            "--site",
                            str(site_path),
                            "configure",
                            "companion",
                            "--non-interactive",
                            "--skip-connectivity-check",
                            "--enable-notify",
                            "--notify-webhook-url",
                            secret,
                        ]
                    )
            payload = json.loads(stdout.getvalue())
            site_config = load_yaml(site_path)

        self.assertEqual(return_code, 0)
        self.assertEqual(site_config["roles"]["companion"]["notifications"]["webhook_url"], secret)
        self.assertEqual(payload["settings"]["notifications"]["webhook_url"], REDACTED_VALUE)
        self.assertEqual(
            artifact_runs[0].json["configure-report.json"]["settings"]["notifications"]["webhook_url"],
            REDACTED_VALUE,
        )
        self.assertNotIn(secret, stdout.getvalue())

    def test_redaction_removes_webhook_urls_from_error_strings(self):
        payload = {
            "error": (
                "HTTPSConnectionPool(host='hooks.slack.com', port=443): "
                "Max retries exceeded with url: /services/T000/B000/SECRET"
            ),
            "full_url": "https://hooks.slack.com/services/T000/B000/SECRET",
        }

        redacted = redact_sensitive(payload)

        self.assertNotIn("SECRET", str(redacted))
        self.assertEqual(redacted["full_url"], REDACTED_VALUE)

    def test_cli_configure_scout_non_interactive_writes_drive_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            result = run_cli(
                "--site",
                str(site_path),
                "configure",
                "scout",
                "--non-interactive",
                "--skip-connectivity-check",
                "--ssh-host",
                "192.0.2.10",
                "--ssh-user",
                "linaro",
                "--workspace-dir",
                "/userdata/catkin_ws/src/auto-scout",
                "--ros-master-uri",
                "http://192.0.2.10:11311",
                "--advertise-host",
                "192.0.2.10",
                "--service-user",
                "linaro",
                "--service-group",
                "linaro",
                "--drive-model",
                "omni",
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            site_config = load_yaml(site_path)

        self.assertEqual(site_config["roles"]["scout"]["motion"]["drive_model"], "omni")

    def test_cli_probe_progress_goes_to_stderr_and_stdout_stays_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            site_config = default_site_config()
            scout = site_config["roles"]["scout"]
            scout["ssh"]["host"] = "192.0.2.10"
            scout["ros"]["master_uri"] = "http://192.0.2.10:11311"
            scout["ros"]["advertise_host"] = "192.0.2.10"
            write_yaml(site_path, site_config)
            stdout = io.StringIO()
            stderr = io.StringIO()

            def fake_probe(site_config, observe_motion_seconds, exercise_cmd_vel, artifact_run, progress=None):
                self.assertEqual(observe_motion_seconds, 0)
                self.assertFalse(exercise_cmd_vel)
                if progress:
                    progress("probe: fake live probe progress")
                return {
                    "ok": True,
                    "observed": {},
                    "inferred_capabilities": {},
                    "config_mismatch_suggestions": [],
                    "errors": [],
                }

            with patch.object(cli, "probe_scout_capabilities", side_effect=fake_probe):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = cli.main(
                        [
                            "--site",
                            str(site_path),
                            "probe",
                            "scout",
                            "--skip-connectivity-check",
                            "--observe-motion",
                            "0",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("probe: Checking scout connectivity", stderr.getvalue())
        self.assertIn("probe: fake live probe progress", stderr.getvalue())

    def test_cli_probe_quiet_suppresses_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            site_config = default_site_config()
            scout = site_config["roles"]["scout"]
            scout["ssh"]["host"] = "192.0.2.10"
            scout["ros"]["master_uri"] = "http://192.0.2.10:11311"
            scout["ros"]["advertise_host"] = "192.0.2.10"
            write_yaml(site_path, site_config)
            stdout = io.StringIO()
            stderr = io.StringIO()
            observed_progress_callbacks = []

            def fake_probe(site_config, observe_motion_seconds, exercise_cmd_vel, artifact_run, progress=None):
                observed_progress_callbacks.append(progress)
                return {
                    "ok": True,
                    "observed": {},
                    "inferred_capabilities": {},
                    "config_mismatch_suggestions": [],
                    "errors": [],
                }

            with patch.object(cli, "probe_scout_capabilities", side_effect=fake_probe):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = cli.main(
                        [
                            "--site",
                            str(site_path),
                            "probe",
                            "scout",
                            "--skip-connectivity-check",
                            "--observe-motion",
                            "0",
                            "--quiet",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(observed_progress_callbacks, [None])

    def test_cli_notify_test_posts_slack_payload(self):
        artifact_runs = []

        class FakeArtifactRun:
            def __init__(self, name):
                self.name = name
                self.json = {}
                artifact_runs.append(self)

            def write_json(self, name, payload):
                self.json[name] = payload

            def write_text(self, name, content):
                pass

            def log(self, message):
                pass

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            site_config = default_site_config()
            site_config["roles"]["companion"]["capabilities"]["notify"] = True
            site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
            write_yaml(site_path, site_config)
            posts = []
            stdout = io.StringIO()

            def fake_post(url, payload, timeout=None):
                posts.append({"url": url, "json": payload, "timeout": timeout})
                return FakeResponse()

            with patch.object(cli, "ArtifactRun", FakeArtifactRun):
                with patch.object(cli, "_post_json", side_effect=fake_post):
                    with redirect_stdout(stdout):
                        return_code = cli.main(
                            [
                                "--site",
                                str(site_path),
                                "notify",
                                "test",
                                "--message",
                                "Auto-Scout test from unit tests",
                            ]
                        )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(return_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(posts[0]["url"], "https://notify.example.test/auto-scout")
        self.assertEqual(posts[0]["json"]["text"], "Auto-Scout test from unit tests")
        self.assertIn("blocks", posts[0]["json"])
        self.assertNotIn("https://notify.example.test/auto-scout", stdout.getvalue())
        self.assertTrue(artifact_runs[0].json["notify-test-report.json"]["sent"])

    def test_cli_configure_companion_prompt_accepts_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            result = run_cli_with_input(
                "--site",
                str(site_path),
                "configure",
                "companion",
                "--prompt",
                "--skip-connectivity-check",
                input_text=(
                    "\n"
                    "prompted-pi.example.test\n"
                    "automark\n"
                    "2200\n"
                    "agent\n"
                    "/home/automark/auto-scout\n"
                    "http://192.0.2.10:11311\n"
                    "companion.example.test\n"
                    "automark\n"
                    "automark\n"
                    "/var/lib/auto-scout\n"
                ),
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = parse_json_output(result.stdout)
            site_config = load_yaml(site_path)

        self.assertTrue(payload["prompted"])
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["host"], "prompted-pi.example.test")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["user"], "automark")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["port"], 2200)
        self.assertEqual(site_config["roles"]["companion"]["storage"]["events_dir"], "/var/lib/auto-scout/events")

    def test_markdown_link_helper_flags_local_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            readme_path = temp_root / "README.md"
            readme_path.write_text(
                "[bad](/Users/example/auto-scout/docs/setup_guide.md)\n[good](docs/setup_guide.md)\n",
                encoding="utf-8",
            )

            issues = find_local_markdown_link_targets(temp_root)

        self.assertEqual(issues, ["README.md -> /Users/example/auto-scout/docs/setup_guide.md"])

    def test_runtime_mode_reports_pose_gate_pass_on_default_site(self):
        result = run_validator("--mode", "runtime", "--role", "system", "--json", "--no-live-probe")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        report = json.loads(result.stdout)
        pose_gate = next(item for item in report["checks"] if item["name"] == "runtime.pose_gate")

        self.assertEqual(pose_gate["status"], "pass")
        self.assertIn("Declared pose provider", pose_gate["details"][0])

    def test_default_site_config_uses_diff_drive_model_and_placeholder_hosts(self):
        site_config = default_site_config()
        scout = site_config["roles"]["scout"]

        self.assertEqual(scout["motion"]["drive_model"], "diff")
        self.assertEqual(scout["topics"]["camera_compressed"], "/camera/image_raw/compressed")
        self.assertEqual(scout["topics"]["vendor_camera_jpg"], "/CoreNode/jpg")
        self.assertEqual(scout["topics"]["scout_tof"], "/SensorNode/tof")
        self.assertEqual(scout["topics"]["tof_range"], "/scout/tof")
        self.assertEqual(scout["topics"]["scout_imu"], "/SensorNode/imu")
        self.assertEqual(scout["topics"]["imu_data"], "/scout/imu/data")
        self.assertEqual(scout["topics"]["planner_cmd_vel"], "/scout/cmd_vel_planner")
        self.assertEqual(scout["topics"]["safety_state"], "/scout/safety_state")
        self.assertEqual(scout["topics"]["battery_status"], "/SensorNode/simple_battery_status")
        self.assertEqual(scout["topics"]["battery_guard_state"], "/scout/battery_guard_state")
        self.assertEqual(scout["topics"]["battery_guard_control"], "/scout/battery_guard_control")
        self.assertEqual(scout["topics"]["vendor_dock_status"], "/CoreNode/going_home_status")
        self.assertEqual(scout["adapters"]["camera"], "vendor_jpg_bridge")
        self.assertTrue(scout["capabilities"]["tof"])
        self.assertTrue(scout["capabilities"]["imu"])
        self.assertTrue(site_config["roles"]["scout"]["ssh"]["host"].endswith(".invalid"))
        self.assertTrue(site_config["roles"]["companion"]["ssh"]["host"].endswith(".invalid"))

    def test_runtime_mode_reports_pose_gate_failure_on_unverified_site_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            site_config = load_yaml(REPO_ROOT / "config" / "site.yaml")
            site_config["roles"]["scout"]["capabilities"]["pose"] = False
            site_config["roles"]["scout"]["capabilities"]["motion"] = False
            site_config["roles"]["companion"]["capabilities"]["pose"] = False
            write_yaml(site_path, site_config)
            result = run_validator("--mode", "runtime", "--role", "system", "--json", "--site", str(site_path), "--no-live-probe")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        report = json.loads(result.stdout)
        pose_gate = next(item for item in report["checks"] if item["name"] == "runtime.pose_gate")
        self.assertEqual(pose_gate["status"], "fail")
        self.assertIn("Pose remains", pose_gate["summary"])

    def test_smoke_loop_gate_passes_with_real_notification_config(self):
        site_config = default_site_config()
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
        mission_config, _ = load_mission_config("smoke_loop")

        gate = evaluate_smoke_loop_gate(site_config, mission_config)

        self.assertTrue(gate["ok"], msg=gate["issues"])

    def test_smoke_loop_gate_fails_when_notify_url_is_empty(self):
        site_config = default_site_config()
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = ""
        mission_config, _ = load_mission_config("smoke_loop")

        gate = evaluate_smoke_loop_gate(site_config, mission_config)

        self.assertFalse(gate["ok"])
        self.assertTrue(any("webhook_url is empty" in issue for issue in gate["issues"]))

    def test_system_validation_checks_companion_readiness_remotely_when_not_on_companion(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ssh"]["host"] = "moorebot-scout.local"
        site_config["roles"]["scout"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "moorebot-scout.local"
        site_config["roles"]["companion"]["ssh"]["host"] = "auto-scout-pi5.local"
        site_config["roles"]["companion"]["ssh"]["user"] = "automark"
        site_config["roles"]["companion"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"
        site_config["roles"]["companion"]["ros"]["advertise_host"] = "auto-scout-pi5.local"
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
        commands = []

        class FakeRemoteResult:
            def __init__(self, ok=True, stdout="", stderr=""):
                self.ok = ok
                self.stdout = stdout
                self.stderr = stderr

        def fake_run_companion_command(companion, body):
            commands.append(body)
            if "docker ps" in body:
                return FakeRemoteResult(stdout="auto-scout-melodic\n")
            if "docker exec" in body and "moorebot-scout.local" in body:
                return FakeRemoteResult(stdout="192.168.0.199 moorebot-scout.local\n")
            if "docker exec" in body and "auto-scout-pi5.local" in body:
                return FakeRemoteResult(stdout="192.168.0.88 auto-scout-pi5.local\n")
            return FakeRemoteResult(stdout="")

        original_match = validator._role_matches_local_host
        original_run = validator._run_companion_command
        try:
            validator._role_matches_local_host = lambda role_settings: False
            validator._run_companion_command = fake_run_companion_command
            report = validator.ReportBuilder("runtime", "likely_companion", "system")
            validator.add_runtime_checks(
                report,
                site_config,
                str(REPO_ROOT / "config" / "site_local.yaml"),
                "system",
                "likely_companion",
                live_probe_enabled=False,
                connectivity_check_enabled=False,
            )
            payload = report.build()
        finally:
            validator._role_matches_local_host = original_match
            validator._run_companion_command = original_run

        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["runtime.companion_readiness"]["status"], "pass")
        self.assertEqual(checks["runtime.companion_readiness"]["evidence"]["check_mode"], "ssh")
        self.assertEqual(checks["runtime.container_hostname_resolution"]["status"], "pass")
        self.assertTrue(any("/srv/auto-scout/maps" in command for command in commands))
        self.assertTrue(any("docker ps" in command for command in commands))
        self.assertTrue(any("docker exec auto-scout-melodic getent hosts moorebot-scout.local" in command for command in commands))

    def test_cli_deploy_scout_dry_run(self):
        result = run_cli(
            "deploy",
            "scout",
            "--dry-run",
            "--skip-connectivity-check",
            "--non-interactive",
            "--ssh-host",
            "192.0.2.10",
            "--ssh-user",
            "linaro",
            "--workspace-dir",
            "/userdata/catkin_ws/src/auto-scout",
            "--ros-master-uri",
            "http://192.0.2.10:11311",
            "--advertise-host",
            "192.0.2.10",
            "--service-user",
            "linaro",
            "--service-group",
            "linaro",
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["role"], "scout")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["service"], "auto-scout-scout-runtime.service")
        self.assertEqual(payload["ros_log_dir"], "/userdata/auto-scout/ros-logs")

    def test_scout_deploy_site_inventory_omits_companion_webhook_secret(self):
        class FakeRunner:
            def __init__(self):
                self.payload = None

            def copy_to_remote(self, ssh_config, local_path, remote_path):
                self.payload = load_yaml(local_path)

        site_config = default_site_config()
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
        runner = FakeRunner()

        _copy_site_inventory_to_remote(
            runner,
            site_config["roles"]["scout"]["ssh"],
            site_config["roles"]["scout"]["workspace_dir"],
            site_config,
            role="scout",
        )

        companion = runner.payload["roles"]["companion"]
        self.assertFalse(companion["capabilities"]["notify"])
        self.assertEqual(companion["notifications"]["webhook_url"], "")

    def test_companion_deploy_site_inventory_keeps_companion_webhook_secret(self):
        class FakeRunner:
            def __init__(self):
                self.payload = None

            def copy_to_remote(self, ssh_config, local_path, remote_path):
                self.payload = load_yaml(local_path)

        site_config = default_site_config()
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
        runner = FakeRunner()

        _copy_site_inventory_to_remote(
            runner,
            site_config["roles"]["companion"]["ssh"],
            site_config["roles"]["companion"]["workspace_dir"],
            site_config,
            role="companion",
        )

        companion = runner.payload["roles"]["companion"]
        self.assertTrue(companion["capabilities"]["notify"])
        self.assertEqual(companion["notifications"]["webhook_url"], "https://notify.example.test/auto-scout")

    def test_rendered_services_use_saved_ros_endpoints(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "moorebot-scout.local"
        site_config["roles"]["scout"]["motion"]["drive_model"] = "omni"
        site_config["roles"]["companion"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"
        site_config["roles"]["companion"]["ros"]["advertise_host"] = "auto-scout-pi5.local"

        scout_service = _render_scout_service(site_config["roles"]["scout"])
        companion_service = _render_companion_service(site_config["roles"]["companion"], site_config["roles"]["scout"])

        self.assertIn("Environment=ROS_MASTER_URI=http://moorebot-scout.local:11311", scout_service)
        self.assertIn("Environment=ROS_HOSTNAME=moorebot-scout.local", scout_service)
        self.assertIn("Environment=ROS_LOG_DIR=/userdata/auto-scout/ros-logs", scout_service)
        self.assertIn("Environment=ROS_OS_OVERRIDE=debian:stretch", scout_service)
        self.assertIn("Environment=AUTO_SCOUT_ENABLE_CAMERA=false", scout_service)
        self.assertIn(
            "Environment=AUTO_SCOUT_SITE_CONFIG={}/config/site_local.yaml".format(
                site_config["roles"]["scout"]["workspace_dir"]
            ),
            scout_service,
        )
        self.assertIn("Environment=AUTO_SCOUT_ROS_MASTER_URI=http://moorebot-scout.local:11311", companion_service)
        self.assertIn("Environment=AUTO_SCOUT_ROS_HOSTNAME=auto-scout-pi5.local", companion_service)
        self.assertIn("Environment=AUTO_SCOUT_ROS_LOG_DIR=/srv/auto-scout/ros-logs", companion_service)
        self.assertIn(
            "Environment=AUTO_SCOUT_SITE_CONFIG={}/config/site_local.yaml".format(
                site_config["roles"]["companion"]["workspace_dir"]
            ),
            companion_service,
        )
        self.assertIn("Environment=AUTO_SCOUT_ODOM_MODEL_TYPE=omni", companion_service)

    def test_rendered_ros_log_cleanup_units_bound_age_and_size(self):
        service_text = _render_ros_log_cleanup_service(
            "/userdata/catkin_ws/src/auto-scout",
            "linaro",
            "linaro",
            "/userdata/auto-scout/ros-logs",
            legacy_log_dirs=["/home/linaro/.ros/log"],
        )
        timer_text = _render_ros_log_cleanup_timer()

        self.assertIn("Environment=ROS_LOG_DIR=/userdata/auto-scout/ros-logs", service_text)
        self.assertIn("Environment=AUTO_SCOUT_ROS_LOG_MAX_AGE_DAYS=7", service_text)
        self.assertIn("Environment=AUTO_SCOUT_ROS_LOG_MAX_BYTES=104857600", service_text)
        self.assertIn("Nice=10", service_text)
        self.assertIn("CPUSchedulingPolicy=batch", service_text)
        self.assertIn("IOSchedulingClass=idle", service_text)
        self.assertIn("--path /userdata/auto-scout/ros-logs", service_text)
        self.assertIn("--path /home/linaro/.ros/log", service_text)
        self.assertIn("OnBootSec=5min", timer_text)
        self.assertIn("OnUnitActiveSec=1d", timer_text)
        self.assertIn("Persistent=true", timer_text)

    def test_service_rendering_fails_fast_on_placeholder_ros_endpoints(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["motion"]["drive_model"] = "diff"

        with self.assertRaises(ValueError):
            _render_scout_service(site_config["roles"]["scout"])

        with self.assertRaises(ValueError):
            _render_companion_service(site_config["roles"]["companion"], site_config["roles"]["scout"])

    def test_cli_deploy_companion_fails_fast_on_placeholder_ros_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            write_yaml(site_path, default_site_config())

            result = run_cli("--site", str(site_path), "deploy", "companion", "--dry-run", "--non-interactive")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        payload = parse_json_output(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("generated placeholder", payload["error"])

    def test_companion_startup_contract_uses_mapping_default_and_explicit_ros_env(self):
        compose_text = (REPO_ROOT / "container" / "docker-compose.yml").read_text(encoding="utf-8")
        start_script = (REPO_ROOT / "scripts" / "start_companion_stack.sh").read_text(encoding="utf-8")
        scout_start_script = (REPO_ROOT / "scripts" / "start_scout_runtime.sh").read_text(encoding="utf-8")
        known_hosts_script = (REPO_ROOT / "scripts" / "provision_pi_known_hosts.sh").read_text(encoding="utf-8")
        companion_launch = (REPO_ROOT / "launch" / "companion_runtime.launch").read_text(encoding="utf-8")
        navigation_launch = (REPO_ROOT / "launch" / "navigation.launch").read_text(encoding="utf-8")
        env_example = (REPO_ROOT / "container" / ".env.example").read_text(encoding="utf-8")

        self.assertIn("localization_mode:=${AUTO_SCOUT_LOCALIZATION_MODE:-false}", compose_text)
        self.assertIn("AUTO_SCOUT_SITE_CONFIG: ${AUTO_SCOUT_SITE_CONFIG}", compose_text)
        self.assertIn("AUTO_SCOUT_ODOM_MODEL_TYPE: ${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}", compose_text)
        self.assertIn("ROS_LOG_DIR: ${AUTO_SCOUT_ROS_LOG_DIR:-/srv/auto-scout/ros-logs}", compose_text)
        self.assertIn("/run/avahi-daemon/socket:/run/avahi-daemon/socket", compose_text)
        self.assertIn("/run/dbus/system_bus_socket:/run/dbus/system_bus_socket", compose_text)
        self.assertIn("source /opt/catkin_ws/devel/setup.bash", compose_text)
        self.assertIn('AUTO_SCOUT_SITE_CONFIG="${AUTO_SCOUT_SITE_CONFIG:-${DEFAULT_SITE_CONFIG}}"', start_script)
        self.assertIn("export AUTO_SCOUT_SITE_CONFIG", start_script)
        self.assertIn('AUTO_SCOUT_LOCALIZATION_MODE="${AUTO_SCOUT_LOCALIZATION_MODE:-false}"', start_script)
        self.assertIn('AUTO_SCOUT_ODOM_MODEL_TYPE="${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}"', start_script)
        self.assertIn('AUTO_SCOUT_ROS_LOG_DIR="${AUTO_SCOUT_ROS_LOG_DIR:-${AUTO_SCOUT_STORAGE_ROOT}/ros-logs}"', start_script)
        self.assertIn("export AUTO_SCOUT_ROS_LOG_DIR", start_script)
        self.assertIn('export ROS_OS_OVERRIDE="${ROS_OS_OVERRIDE:-debian:stretch}"', scout_start_script)
        self.assertIn('CAMERA_ENABLED="${AUTO_SCOUT_ENABLE_CAMERA:-false}"', scout_start_script)
        self.assertIn('enable_camera:="${CAMERA_ENABLED}"', scout_start_script)
        self.assertIn("require_env AUTO_SCOUT_ROS_MASTER_URI", start_script)
        self.assertIn("require_env AUTO_SCOUT_ROS_HOSTNAME", start_script)
        self.assertNotIn("moorebot-scout.local", start_script)
        self.assertIn('<arg name="site_file" default="$(find auto-scout)/config/site.yaml" />', companion_launch)
        self.assertIn('<arg name="localization_mode" default="false" />', companion_launch)
        self.assertIn('name="battery_map_return_controller"', companion_launch)
        self.assertIn('name="vendor_jpg_bridge"', companion_launch)
        self.assertIn('<arg name="odom_model_type" default="$(optenv AUTO_SCOUT_ODOM_MODEL_TYPE diff)"/>', navigation_launch)
        self.assertIn('<arg name="planner_cmd_vel" default="/scout/cmd_vel_planner"/>', navigation_launch)
        self.assertIn('name="robot_state_publisher"', navigation_launch)
        self.assertIn('<remap from="cmd_vel" to="$(arg planner_cmd_vel)"/>', navigation_launch)
        self.assertIn('<param name="odom_alpha5" value="0.2"/>', navigation_launch)
        self.assertIn("AUTO_SCOUT_ROS_MASTER_URI=http://<scout-host-or-ip>:11311", env_example)
        self.assertIn("AUTO_SCOUT_SITE_CONFIG=/opt/catkin_ws/src/auto-scout/config/site_local.yaml", env_example)
        self.assertIn("AUTO_SCOUT_ODOM_MODEL_TYPE=diff", env_example)
        self.assertIn("AUTO_SCOUT_ROS_LOG_DIR=/srv/auto-scout/ros-logs", env_example)
        self.assertIn("ssh-keyscan -H", known_hosts_script)
        self.assertIn("moorebot-scout.local", known_hosts_script)
        self.assertIn("auto-scout-pi5.local", known_hosts_script)
        self.assertNotIn("StrictHostKeyChecking=no", known_hosts_script)

    def test_smoke_loop_command_runs_inside_companion_container(self):
        site_config = default_site_config()
        site_config["roles"]["companion"]["ros"]["container_name"] = "auto-scout-melodic"

        class DummyArtifactRun:
            path = REPO_ROOT / "artifacts" / "runs" / "smoke-loop" / "run-001"

        command = _build_smoke_loop_remote_command(
            site_config["roles"]["companion"],
            str(REPO_ROOT / "config" / "missions" / "smoke_loop.yaml"),
            DummyArtifactRun(),
        )

        self.assertIn("docker exec auto-scout-melodic /bin/bash -lc", command)
        self.assertIn("source /opt/ros/melodic/setup.bash", command)
        self.assertIn("python2 src/scout_navigation_controller.py", command)
        self.assertNotIn("python3 src/scout_navigation_controller.py", command)
        self.assertIn("/opt/catkin_ws/src/auto-scout/config/site_local.yaml", command)

    def test_smoke_loop_remote_preflight_payload_is_returned(self):
        site_config = default_site_config()
        site_config["roles"]["companion"]["capabilities"]["notify"] = True
        site_config["roles"]["companion"]["notifications"]["webhook_url"] = "https://notify.example.test/auto-scout"
        mission_config, mission_path = load_mission_config("smoke_loop")

        class FakeArtifactRun:
            path = REPO_ROOT / "artifacts" / "runs" / "smoke-loop" / "run-001"

            def __init__(self):
                self.json = {}
                self.text = {}

            def write_json(self, name, payload):
                self.json[name] = payload

            def write_text(self, name, content):
                self.text[name] = content

        class FakeRemoteResult:
            ok = True
            stdout = (
                'ros log line\n'
                '{"ok": false, "phase": "preflight", "reason": "battery_too_low_to_leave_dock", '
                '"battery_percent": 49.9, "battery_guard_state": {"mode": "charging"}}\n'
            )
            stderr = ""

        class FakeRunner:
            def __init__(self, artifact_run=None, dry_run=False):
                self.artifact_run = artifact_run
                self.dry_run = dry_run

            def run_remote(self, ssh_config, remote_command, check=True):
                return FakeRemoteResult()

        artifact_run = FakeArtifactRun()
        with patch.object(mission_runner, "CommandRunner", FakeRunner):
            result = mission_runner.run_smoke_loop(
                site_config,
                str(REPO_ROOT / "config" / "site_local.yaml"),
                mission_config,
                mission_path,
                artifact_run,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["reason"], "battery_too_low_to_leave_dock")
        self.assertAlmostEqual(result["battery_percent"], 49.9)
        self.assertIn("remote.stdout.txt", artifact_run.text)
        self.assertEqual(artifact_run.json["remote-mission-result.json"]["reason"], "battery_too_low_to_leave_dock")

    def test_cli_smoke_loop_dry_run_fails_fast_on_unverified_site(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "site.yaml"
            write_yaml(site_path, default_site_config())
            result = run_cli(
                "--site",
                str(site_path),
                "run",
                "smoke-loop",
                "--dry-run",
                "--skip-connectivity-check",
            )

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], "preflight")
        self.assertTrue(any("notify" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()

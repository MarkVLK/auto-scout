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

from check_scout_compatibility import find_local_markdown_link_targets
from auto_scout.deploy import _render_companion_service
from auto_scout.deploy import _render_scout_service
from auto_scout.mission_runner import _build_smoke_loop_remote_command
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
                "http://192.0.2.10:11311",
                "--advertise-host",
                "companion.example.test",
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
        self.assertEqual(site_config["roles"]["companion"]["ros"]["master_uri"], "http://192.0.2.10:11311")
        self.assertEqual(site_config["roles"]["companion"]["ros"]["advertise_host"], "companion.example.test")
        self.assertEqual(site_config["roles"]["companion"]["storage"]["maps_dir"], "/mnt/auto-scout/maps")

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

        self.assertEqual(site_config["roles"]["scout"]["motion"]["drive_model"], "diff")
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

    def test_rendered_services_use_saved_ros_endpoints(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ros"]["master_uri"] = "http://192.0.2.10:11311"
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "192.0.2.10"
        site_config["roles"]["scout"]["motion"]["drive_model"] = "omni"
        site_config["roles"]["companion"]["ros"]["master_uri"] = "http://192.0.2.10:11311"
        site_config["roles"]["companion"]["ros"]["advertise_host"] = "companion.example.test"

        scout_service = _render_scout_service(site_config["roles"]["scout"])
        companion_service = _render_companion_service(site_config["roles"]["companion"], site_config["roles"]["scout"])

        self.assertIn("Environment=ROS_MASTER_URI=http://192.0.2.10:11311", scout_service)
        self.assertIn("Environment=ROS_HOSTNAME=192.0.2.10", scout_service)
        self.assertIn(
            "Environment=AUTO_SCOUT_SITE_CONFIG={}/config/site_local.yaml".format(
                site_config["roles"]["scout"]["workspace_dir"]
            ),
            scout_service,
        )
        self.assertIn("Environment=AUTO_SCOUT_ROS_MASTER_URI=http://192.0.2.10:11311", companion_service)
        self.assertIn("Environment=AUTO_SCOUT_ROS_HOSTNAME=companion.example.test", companion_service)
        self.assertIn(
            "Environment=AUTO_SCOUT_SITE_CONFIG={}/config/site_local.yaml".format(
                site_config["roles"]["companion"]["workspace_dir"]
            ),
            companion_service,
        )
        self.assertIn("Environment=AUTO_SCOUT_ODOM_MODEL_TYPE=omni", companion_service)

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
        companion_launch = (REPO_ROOT / "launch" / "companion_runtime.launch").read_text(encoding="utf-8")
        navigation_launch = (REPO_ROOT / "launch" / "navigation.launch").read_text(encoding="utf-8")
        env_example = (REPO_ROOT / "container" / ".env.example").read_text(encoding="utf-8")

        self.assertIn("localization_mode:=${AUTO_SCOUT_LOCALIZATION_MODE:-false}", compose_text)
        self.assertIn("AUTO_SCOUT_SITE_CONFIG: ${AUTO_SCOUT_SITE_CONFIG}", compose_text)
        self.assertIn("AUTO_SCOUT_ODOM_MODEL_TYPE: ${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}", compose_text)
        self.assertIn('AUTO_SCOUT_SITE_CONFIG="${AUTO_SCOUT_SITE_CONFIG:-${DEFAULT_SITE_CONFIG}}"', start_script)
        self.assertIn("export AUTO_SCOUT_SITE_CONFIG", start_script)
        self.assertIn('AUTO_SCOUT_LOCALIZATION_MODE="${AUTO_SCOUT_LOCALIZATION_MODE:-false}"', start_script)
        self.assertIn('AUTO_SCOUT_ODOM_MODEL_TYPE="${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}"', start_script)
        self.assertIn("require_env AUTO_SCOUT_ROS_MASTER_URI", start_script)
        self.assertIn("require_env AUTO_SCOUT_ROS_HOSTNAME", start_script)
        self.assertNotIn("moorebot-scout.local", start_script)
        self.assertIn('<arg name="site_file" default="$(optenv AUTO_SCOUT_SITE_CONFIG $(find auto-scout)/config/site.yaml)" />', companion_launch)
        self.assertIn('<arg name="localization_mode" default="false" />', companion_launch)
        self.assertIn('<arg name="odom_model_type" default="$(optenv AUTO_SCOUT_ODOM_MODEL_TYPE diff)"/>', navigation_launch)
        self.assertIn('<param name="odom_alpha5" value="0.2"/>', navigation_launch)
        self.assertIn("AUTO_SCOUT_ROS_MASTER_URI=http://<scout-ip>:11311", env_example)
        self.assertIn("AUTO_SCOUT_SITE_CONFIG=/opt/catkin_ws/src/auto-scout/config/site_local.yaml", env_example)
        self.assertIn("AUTO_SCOUT_ODOM_MODEL_TYPE=diff", env_example)

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

    def test_cli_smoke_loop_dry_run_fails_fast_on_unverified_site(self):
        result = run_cli("run", "smoke-loop", "--dry-run", "--skip-connectivity-check")

        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], "preflight")
        self.assertTrue(any("notify" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Canonical validator for the clean-slate Auto-Scout reset."""

import argparse
import ast
import json
import os
import platform
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.mission_config import load_mission_config
from auto_scout.mission_runner import evaluate_smoke_loop_gate
from auto_scout.site_config import load_site_config, role_config
from auto_scout.yaml_loader import load_yaml
from config_utils import load_scout_config


README_REQUIRED_STRINGS = [
    "companion-first",
    "config/site.yaml",
    "config/missions/smoke_loop.yaml",
    "auto-scout",
    "scout-runtime",
    "companion-runtime",
]

ACTIVE_RUNTIME_STRINGS = {
    "src/scout_web_interface.py": ["retired", "legacy/scout_web_interface_legacy.py"],
    "src/voice_command_interface.py": ["retired", "legacy/voice_command_interface_legacy.py"],
}

DISALLOWED_ACTIVE_RUNTIME_STRINGS = [
    "torchvision",
    "flask_socketio",
    "speech_recognition",
    "ORB_create",
    "visual_odometry",
]

STATIC_PYTHON_DIRS = [
    "src",
    "tests",
    "tools",
    "scripts",
]


def run_command(command):
    """Run a command and return a structured result."""
    import subprocess

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": None,
        }

    return {
        "ok": result.returncode == 0,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "returncode": result.returncode,
    }


def detect_total_memory_bytes():
    """Best-effort memory detection."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * page_count)
    except (AttributeError, ValueError, OSError):
        return None


def load_os_release():
    """Return `/etc/os-release` data when present."""
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}

    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def detect_runtime_profile():
    """Best-effort local role detection."""
    machine = platform.machine().lower()
    username = os.environ.get("USER", "")

    scout_markers = [
        Path("/home/linaro").exists(),
        username == "linaro",
        Path("/usr/local/lib/librollereye.so").exists(),
        Path("/usr/bin/rollereye").exists(),
    ]

    if any(scout_markers):
        return "likely_scout"

    system_name = platform.system().lower()
    if system_name in ["darwin", "windows"]:
        return "likely_companion"
    if machine in ["x86_64", "amd64", "arm64", "aarch64"]:
        return "likely_companion"
    return "unknown"


def resolve_role(requested_role, runtime_profile):
    """Resolve the effective validation role."""
    if requested_role != "auto":
        return requested_role
    if runtime_profile == "likely_scout":
        return "scout"
    if runtime_profile == "likely_companion":
        return "companion"
    return "system"


def parse_python_function_names(path):
    """Return all function names found in a Python file."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def resolve_find_expression(package_name, value):
    """Resolve simple `$(find package)` expressions to local paths."""
    if not value:
        return None

    prefix = "$(find {})/".format(package_name)
    if value.startswith(prefix):
        return REPO_ROOT / value[len(prefix):]
    return None


class ReportBuilder:
    """Collect structured validation results."""

    def __init__(self, mode, runtime_profile, effective_role):
        self.mode = mode
        self.runtime_profile = runtime_profile
        self.effective_role = effective_role
        self.checks = []

    def add(self, name, status, summary, details=None, evidence=None):
        self.checks.append(
            {
                "name": name,
                "status": status,
                "summary": summary,
                "details": details or [],
                "evidence": evidence or {},
            }
        )

    def build(self):
        counts = {
            "pass": 0,
            "warn": 0,
            "fail": 0,
            "skip": 0,
            "info": 0,
        }

        for check in self.checks:
            counts[check["status"]] = counts.get(check["status"], 0) + 1

        return {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "repo_root": str(REPO_ROOT),
            "mode": self.mode,
            "runtime_profile": self.runtime_profile,
            "role": self.effective_role,
            "summary": {
                "ok": counts["fail"] == 0,
                "counts": counts,
            },
            "checks": self.checks,
        }


def add_repo_checks(report, site_config, site_path, project_config, config_path):
    """Validate repo contracts against the clean-slate architecture."""
    readme_path = REPO_ROOT / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    missing_strings = [item for item in README_REQUIRED_STRINGS if item not in readme_text]
    if missing_strings:
        report.add(
            "repo.readme_contract",
            "fail",
            "README is missing clean-slate runtime references",
            details=["Missing text: {}".format(", ".join(missing_strings))],
        )
    else:
        report.add(
            "repo.readme_contract",
            "pass",
            "README reflects the clean-slate scout/companion split",
            evidence={"readme_path": str(readme_path)},
        )

    inventory_issues = []
    for role_name in ["scout", "companion"]:
        role = site_config.get("roles", {}).get(role_name)
        if not isinstance(role, dict):
            inventory_issues.append("config/site.yaml missing role '{}'".format(role_name))
            continue

        if "ssh" not in role:
            inventory_issues.append("role '{}' is missing ssh settings".format(role_name))
        if "workspace_dir" not in role:
            inventory_issues.append("role '{}' is missing workspace_dir".format(role_name))
        if "capabilities" not in role:
            inventory_issues.append("role '{}' is missing capabilities".format(role_name))

    smoke_mission, mission_path = load_mission_config("smoke_loop")
    gate = evaluate_smoke_loop_gate(site_config, smoke_mission)
    if inventory_issues:
        report.add(
            "repo.inventory_contract",
            "fail",
            "Site inventory is incomplete",
            details=inventory_issues,
            evidence={"site_path": site_path},
        )
    else:
        report.add(
            "repo.inventory_contract",
            "pass",
            "Site inventory provides scout and companion roles with explicit capabilities",
            evidence={"site_path": site_path},
        )

    mission_issues = []
    route = smoke_mission.get("route", {}).get("loop_waypoints", [])
    if not route:
        mission_issues.append("smoke_loop mission is missing route.loop_waypoints")
    required_capabilities = smoke_mission.get("preconditions", {}).get("required_capabilities", [])
    for item in ["camera", "scan", "pose"]:
        if item not in required_capabilities:
            mission_issues.append("smoke_loop mission must require '{}'".format(item))
    if not smoke_mission.get("return", {}).get("fallback_waypoint"):
        mission_issues.append("smoke_loop mission must provide a return fallback_waypoint")
    if smoke_mission.get("notification", {}).get("require_capability") != "notify":
        mission_issues.append("smoke_loop notification must require capability 'notify'")

    if mission_issues:
        report.add(
            "repo.mission_contract",
            "fail",
            "Smoke-loop mission contract is incomplete",
            details=mission_issues,
            evidence={"mission_path": mission_path},
        )
    else:
        report.add(
            "repo.mission_contract",
            "pass",
            "Smoke-loop mission contract is explicit and capability-gated",
            evidence={
                "mission_path": mission_path,
                "route_length": len(route),
                "default_gate_ok": gate["ok"],
            },
        )

    launch_issues = []
    expected_nodes = {
        "launch/scout_runtime.launch": ["scout_runtime_agent", "ld19_lidar_driver", "scout_camera_driver"],
        "launch/companion_runtime.launch": ["companion_runtime_agent"],
        "launch/navigation.launch": ["map_server", "amcl", "move_base"],
        "launch/slam_mapping.launch": ["robot_state_publisher", "slam_gmapping"],
    }
    for relative_path, node_names in expected_nodes.items():
        launch_path = REPO_ROOT / relative_path
        if not launch_path.is_file():
            launch_issues.append("{} is missing".format(relative_path))
            continue

        root = ET.parse(str(launch_path)).getroot()
        present_names = {node.attrib.get("name") for node in root.iter("node")}
        missing = [name for name in node_names if name not in present_names]
        if missing:
            launch_issues.append("{} missing nodes: {}".format(relative_path, ", ".join(missing)))

        for element in root.iter("include"):
            resolved = resolve_find_expression("auto-scout", element.attrib.get("file"))
            if resolved and not resolved.is_file():
                launch_issues.append("{} includes missing file {}".format(relative_path, resolved))

    if launch_issues:
        report.add(
            "repo.launch_contract",
            "fail",
            "Launch files do not fully support the clean-slate roles",
            details=launch_issues,
        )
    else:
        report.add(
            "repo.launch_contract",
            "pass",
            "Launch files expose dedicated scout and companion runtimes",
        )

    service_files = [
        "systemd/auto-scout-scout-runtime.service",
        "systemd/auto-scout-companion-runtime.service",
        "container/Dockerfile",
        "container/docker-compose.yml",
        "scripts/start_scout_runtime.sh",
        "scripts/start_companion_stack.sh",
    ]
    missing_service_files = [path for path in service_files if not (REPO_ROOT / path).is_file()]
    if missing_service_files:
        report.add(
            "repo.service_contract",
            "fail",
            "Deployment/runtime service files are incomplete",
            details=missing_service_files,
        )
    else:
        report.add(
            "repo.service_contract",
            "pass",
            "Service and container files exist for both runtime roles",
        )

    cli_issues = []
    for path in [
        "auto-scout",
        "tools/deploy.sh",
        "src/scout_runtime_agent.py",
        "src/companion_runtime_agent.py",
    ]:
        if not (REPO_ROOT / path).is_file():
            cli_issues.append("{} is missing".format(path))

    if cli_issues:
        report.add(
            "repo.cli_contract",
            "fail",
            "CLI entrypoints are incomplete",
            details=cli_issues,
        )
    else:
        report.add(
            "repo.cli_contract",
            "pass",
            "Headless CLI entrypoints are present",
        )

    quarantine_issues = []
    for relative_path, required_strings in ACTIVE_RUNTIME_STRINGS.items():
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for item in required_strings:
            if item not in content:
                quarantine_issues.append("{} missing '{}'".format(relative_path, item))

    active_python_files = []
    for relative_dir in ["src", "tools"]:
        base_dir = REPO_ROOT / relative_dir
        for path in sorted(base_dir.rglob("*.py")):
            if "legacy" in path.parts:
                continue
            active_python_files.append(path)

    for path in active_python_files:
        text = path.read_text(encoding="utf-8")
        for item in DISALLOWED_ACTIVE_RUNTIME_STRINGS:
            if item in text:
                quarantine_issues.append("{} still references '{}'".format(path.relative_to(REPO_ROOT), item))

    for expected_legacy in [
        "legacy/scout_web_interface_legacy.py",
        "legacy/voice_command_interface_legacy.py",
        "legacy/scout-web.service",
        "legacy/dashboard.html",
    ]:
        if not (REPO_ROOT / expected_legacy).is_file():
            quarantine_issues.append("{} is missing".format(expected_legacy))

    if quarantine_issues:
        report.add(
            "repo.legacy_quarantine_contract",
            "fail",
            "Legacy UI/voice surfaces are not fully quarantined",
            details=quarantine_issues,
        )
    else:
        report.add(
            "repo.legacy_quarantine_contract",
            "pass",
            "Legacy UI/voice surfaces are quarantined behind explicit stubs",
        )

    syntax_errors = []
    checked_files = 0
    for relative_dir in STATIC_PYTHON_DIRS:
        base_dir = REPO_ROOT / relative_dir
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            checked_files += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                syntax_errors.append("{}: {}".format(path.relative_to(REPO_ROOT), exc))

    if syntax_errors:
        report.add(
            "repo.code_contract",
            "fail",
            "Python entrypoints contain syntax errors",
            details=syntax_errors,
            evidence={"checked_python_files": checked_files},
        )
    else:
        report.add(
            "repo.code_contract",
            "pass",
            "Python entrypoints parse cleanly",
            evidence={"checked_python_files": checked_files},
        )


def _add_identity_check(report, effective_role, runtime_profile):
    status = "pass"
    summary = "Runtime role and local host profile are aligned closely enough to validate"
    details = [
        "Platform: {}".format(platform.platform()),
        "Architecture: {}".format(platform.machine()),
        "Python: {}".format(sys.version.replace("\n", " ")),
    ]
    os_release = load_os_release()
    if os_release:
        details.append("OS release: {}".format(os_release.get("PRETTY_NAME", "unknown")))

    if effective_role == "scout" and runtime_profile != "likely_scout":
        status = "warn"
        summary = "Scout validation is running from a non-Scout host; only declarative checks can be trusted"
    elif effective_role in ["companion", "system"] and runtime_profile == "unknown":
        status = "warn"
        summary = "Runtime profile is ambiguous; interpret readiness conservatively"

    report.add(
        "runtime.identity",
        status,
        summary,
        details=details,
        evidence={
            "runtime_profile": runtime_profile,
            "role": effective_role,
        },
    )


def _add_site_role_checks(report, site_config, site_path, effective_role):
    roles_to_check = ["scout", "companion"] if effective_role == "system" else [effective_role]
    issues = []
    for role_name in roles_to_check:
        role = role_config(site_config, role_name)
        if "workspace_dir" not in role:
            issues.append("{} missing workspace_dir".format(role_name))
        if "ssh" not in role:
            issues.append("{} missing ssh".format(role_name))

    if issues:
        report.add(
            "runtime.site_contract",
            "fail",
            "Selected role is not fully described in config/site.yaml",
            details=issues,
            evidence={"site_path": site_path},
        )
    else:
        report.add(
            "runtime.site_contract",
            "pass",
            "config/site.yaml describes the selected runtime role(s)",
            evidence={"site_path": site_path},
        )


def _add_scout_checks(report, site_config, runtime_profile):
    scout = role_config(site_config, "scout")
    capabilities = scout.get("capabilities", {})
    devices = scout.get("devices", {})

    issues = []
    if not capabilities.get("vendor_bridge", False):
        issues.append("scout.capabilities.vendor_bridge must be true")
    if not capabilities.get("camera", False):
        issues.append("scout.capabilities.camera must be true")
    if not capabilities.get("scan", False):
        issues.append("scout.capabilities.scan must be true")

    for name in ["camera", "lidar"]:
        if name not in devices:
            issues.append("scout.devices.{} is missing".format(name))

    status = "fail" if issues else "pass"
    summary = "Scout inventory declares the required bridge, camera, and scan capabilities"
    details = issues

    if not issues and runtime_profile == "likely_scout":
        missing_local = [path for path in devices.values() if not Path(path).exists()]
        if missing_local:
            status = "fail"
            summary = "Scout host is missing required device nodes"
            details.extend("Missing device: {}".format(path) for path in missing_local)
        elif not (Path("/usr/bin/rollereye").exists() or Path("/usr/local/lib/librollereye.so").exists()):
            status = "fail"
            summary = "Scout host is missing rollereye/vendor bridge markers"
            details.append("Neither /usr/bin/rollereye nor /usr/local/lib/librollereye.so was found")
    elif not issues:
        status = "warn"
        summary = "Scout capability declarations look correct, but live hardware was not validated locally"

    report.add(
        "runtime.scout_readiness",
        status,
        summary,
        details=details,
        evidence={
            "devices": devices,
            "capabilities": capabilities,
        },
    )


def _add_companion_checks(report, site_config, runtime_profile):
    companion = role_config(site_config, "companion")
    storage = companion.get("storage", {})
    ros_settings = companion.get("ros", {})

    issues = []
    for path in storage.values():
        if not os.path.isabs(path):
            issues.append("Companion storage path must be absolute: {}".format(path))

    compose_file = ros_settings.get("compose_file")
    if not ros_settings.get("containerized", False):
        issues.append("companion.ros.containerized must be true")
    elif not compose_file:
        issues.append("companion.ros.compose_file is missing")
    else:
        compose_path = REPO_ROOT / compose_file
        if not compose_path.is_file():
            issues.append("compose file is missing: {}".format(compose_path))

    status = "fail" if issues else "pass"
    summary = "Companion inventory declares containerized ROS and primary storage"
    details = issues

    if not issues and runtime_profile == "likely_companion":
        missing_dirs = [path for path in storage.values() if not Path(path).exists()]
        if missing_dirs:
            status = "fail"
            summary = "Companion storage directories are missing locally"
            details.extend("Missing directory: {}".format(path) for path in missing_dirs)
        elif not run_command(["docker", "compose", "version"])["ok"]:
            status = "warn"
            summary = "Companion storage exists, but docker compose is not available locally"
    elif not issues:
        status = "warn"
        summary = "Companion configuration looks correct, but local storage/container checks were not run"

    report.add(
        "runtime.companion_readiness",
        status,
        summary,
        details=details,
        evidence={
            "storage": storage,
            "ros": ros_settings,
        },
    )


def _add_resource_check(report):
    home_dir = Path.home()
    disk_total, disk_used, disk_free = shutil.disk_usage(str(home_dir))
    total_memory_bytes = detect_total_memory_bytes()
    details = [
        "Home filesystem total: {:.2f} GB".format(disk_total / float(1024 ** 3)),
        "Home filesystem free: {:.2f} GB".format(disk_free / float(1024 ** 3)),
    ]
    if total_memory_bytes is not None:
        details.append("Detected RAM: {:.2f} GB".format(total_memory_bytes / float(1024 ** 3)))

    report.add(
        "runtime.resources",
        "info",
        "Reported local resource snapshot",
        details=details,
    )


def _add_mission_checks(report, site_config):
    smoke_mission, mission_path = load_mission_config("smoke_loop")
    gate = evaluate_smoke_loop_gate(site_config, smoke_mission)

    mapping_issues = []
    scout = role_config(site_config, "scout")
    companion = role_config(site_config, "companion")
    if not scout.get("capabilities", {}).get("scan", False):
        mapping_issues.append("Scout scan capability is disabled")
    if not companion.get("capabilities", {}).get("pose", False):
        mapping_issues.append("Companion pose capability is disabled")
    if not companion.get("storage", {}).get("maps_dir"):
        mapping_issues.append("Companion maps_dir is missing")

    patrol_issues = []
    if not companion.get("capabilities", {}).get("pose", False):
        patrol_issues.append("Pose capability is required for localization and patrol")
    if not scout.get("capabilities", {}).get("camera", False):
        patrol_issues.append("Camera capability is required for patrol proof capture")

    if mapping_issues:
        report.add(
            "runtime.mission_house_mapping",
            "fail",
            "House mapping is blocked by capability or storage gaps",
            details=mapping_issues,
        )
    else:
        report.add(
            "runtime.mission_house_mapping",
            "pass",
            "House mapping prerequisites are declared",
        )

    if patrol_issues:
        report.add(
            "runtime.mission_room_patrol",
            "fail",
            "Room patrol is blocked by capability gaps",
            details=patrol_issues,
        )
    else:
        report.add(
            "runtime.mission_room_patrol",
            "pass",
            "Room patrol prerequisites are declared",
        )

    smoke_status = "pass"
    smoke_summary = "Smoke-loop mission gate is satisfied"
    if not gate["ok"]:
        smoke_status = "fail"
        smoke_summary = "Smoke-loop mission is blocked by missing capabilities"
    elif not role_config(site_config, "scout").get("capabilities", {}).get("dock", False):
        smoke_status = "warn"
        smoke_summary = "Smoke-loop can run with waypoint fallback, but full dock return is unavailable"

    report.add(
        "runtime.mission_smoke_loop",
        smoke_status,
        smoke_summary,
        details=gate["issues"],
        evidence={"mission_path": mission_path},
    )


def add_runtime_checks(report, site_config, site_path, effective_role, runtime_profile):
    """Validate local/runtime readiness for the selected role."""
    _add_identity_check(report, effective_role, runtime_profile)
    _add_site_role_checks(report, site_config, site_path, effective_role)
    _add_resource_check(report)

    if effective_role in ["scout", "system"]:
        _add_scout_checks(report, site_config, runtime_profile)

    if effective_role in ["companion", "system"]:
        _add_companion_checks(report, site_config, runtime_profile)

    _add_mission_checks(report, site_config)


def build_parser():
    parser = argparse.ArgumentParser(description="Validate Auto-Scout repo and runtime assumptions")
    parser.add_argument("--mode", choices=["repo", "runtime", "all"], default="all")
    parser.add_argument("--role", choices=["auto", "scout", "companion", "system"], default="auto")
    parser.add_argument("--site", default=str(REPO_ROOT / "config" / "site.yaml"))
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "scout_config.yaml"))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--json-out", default=None, help="Write JSON report to a file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    runtime_profile = detect_runtime_profile()
    effective_role = resolve_role(args.role, runtime_profile)
    site_config, site_path = load_site_config(args.site)
    project_config, config_path = load_scout_config(args.config)

    report = ReportBuilder(args.mode, runtime_profile, effective_role)

    if args.mode in ["repo", "all"]:
        add_repo_checks(report, site_config, site_path, project_config, config_path)

    if args.mode in ["runtime", "all"]:
        add_runtime_checks(report, site_config, site_path, effective_role, runtime_profile)

    payload = report.build()
    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("mode: {}".format(payload["mode"]))
        print("role: {}".format(payload["role"]))
        print("summary: {}".format("ok" if payload["summary"]["ok"] else "not ok"))
        for check in payload["checks"]:
            print("[{}] {}: {}".format(check["status"], check["name"], check["summary"]))

    return 0 if payload["summary"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

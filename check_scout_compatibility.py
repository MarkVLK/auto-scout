#!/usr/bin/env python3
"""Canonical validator for the clean-slate Auto-Scout reset."""

import argparse
import ast
import json
import os
import platform
import re
import shlex
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
from auto_scout.live_probe import ProbeExecutor
from auto_scout.live_probe import probe_scout_capabilities
from auto_scout.mission_runner import evaluate_smoke_loop_gate
from auto_scout.network_validation import validate_site_connectivity
from auto_scout.site_config import load_site_config, normalize_drive_model, role_config, role_motion_setting, role_service_identity
from auto_scout.yaml_loader import load_yaml
from config_utils import load_scout_config


README_REQUIRED_STRINGS = [
    "companion-first",
    "config/site.yaml",
    "config/site_local.yaml",
    "config/missions/smoke_loop.yaml",
    "auto-scout",
    "scout-runtime",
    "companion-runtime",
    "ros1_bridge",
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

MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
NATIVE_SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp")
PLACEHOLDER_MARKER = ".invalid"


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


def normalize_markdown_target(target):
    """Normalize a markdown link target for local-path checks."""
    value = (target or "").strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value


def is_local_absolute_markdown_target(target):
    """Return whether a markdown target points at a local filesystem path."""
    value = normalize_markdown_target(target)
    lowered = value.lower()
    return bool(
        value
        and (
            lowered.startswith("file://")
            or value.startswith("/Users/")
            or value.startswith("/home/")
            or re.match(r"^[A-Za-z]:[\\/]", value)
        )
    )


def find_local_markdown_link_targets(root_path):
    """Return repo-relative markdown link issues that target local filesystems."""
    root = Path(root_path)
    issues = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK_PATTERN.findall(text):
            normalized = normalize_markdown_target(target)
            if is_local_absolute_markdown_target(normalized):
                issues.append("{} -> {}".format(path.relative_to(root), normalized))
    return issues


def _is_generated_placeholder(value):
    return PLACEHOLDER_MARKER in str(value or "")


def _native_source_uses_opencv(path):
    text = path.read_text(encoding="utf-8")
    patterns = [
        "#include <opencv",
        "#include \"opencv",
        "cv::",
        "opencv2/",
    ]
    return any(item in text for item in patterns)


def _parse_mode_bits(mode_text):
    if not mode_text or len(mode_text) != 3 or not mode_text.isdigit():
        return None
    return int(mode_text[0]), int(mode_text[1]), int(mode_text[2])


def _has_rw(bits):
    return bits is not None and (bits & 6) == 6


def _service_user_has_device_access(mode_text, owner, group, service_user, service_groups):
    bits = _parse_mode_bits(mode_text)
    if bits is None:
        return False

    user_bits, group_bits, other_bits = bits
    if owner == service_user and _has_rw(user_bits):
        return True
    if group in service_groups and _has_rw(group_bits):
        return True
    if _has_rw(other_bits):
        return True
    return False


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

    markdown_link_issues = find_local_markdown_link_targets(REPO_ROOT)
    if markdown_link_issues:
        report.add(
            "repo.docs_link_contract",
            "fail",
            "Markdown docs still contain local absolute filesystem links",
            details=markdown_link_issues,
        )
    else:
        report.add(
            "repo.docs_link_contract",
            "pass",
            "Markdown docs use repo-relative or web-safe link targets",
        )

    inventory_issues = []
    sample_site_path = REPO_ROOT / "config" / "site.yaml"
    raw_site_config = load_yaml(sample_site_path) if sample_site_path.is_file() else {}
    if not isinstance(raw_site_config, dict):
        raw_site_config = {}
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

    scout_motion = site_config.get("roles", {}).get("scout", {}).get("motion", {})
    raw_roles = raw_site_config.get("roles", {}) if isinstance(raw_site_config.get("roles", {}), dict) else {}
    raw_scout = raw_roles.get("scout", {}) if isinstance(raw_roles.get("scout", {}), dict) else {}
    raw_scout_motion = raw_scout.get("motion", {}) if isinstance(raw_scout.get("motion", {}), dict) else {}
    try:
        normalize_drive_model(scout_motion.get("drive_model"))
    except ValueError as exc:
        inventory_issues.append(str(exc))
    if "drive_model" not in raw_scout_motion:
        inventory_issues.append("config/site.yaml must explicitly set roles.scout.motion.drive_model")

    smoke_mission, mission_path = load_mission_config("smoke_loop")
    gate = evaluate_smoke_loop_gate(site_config, smoke_mission)
    if inventory_issues:
        report.add(
            "repo.inventory_contract",
            "fail",
            "Site inventory is incomplete",
            details=inventory_issues,
            evidence={"site_path": str(sample_site_path)},
        )
    else:
        report.add(
            "repo.inventory_contract",
            "pass",
            "Site inventory provides scout and companion roles with explicit capabilities",
            evidence={"site_path": str(sample_site_path)},
        )

    mission_issues = []
    route = smoke_mission.get("route", {}).get("loop_waypoints", [])
    if not route:
        mission_issues.append("smoke_loop mission is missing route.loop_waypoints")
    required_capabilities = smoke_mission.get("preconditions", {}).get("required_capabilities", [])
    for item in ["camera", "scan", "pose", "motion"]:
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
        "launch/scout_runtime.launch": [
            "scout_runtime_agent",
            "ld19_lidar_driver",
            "scout_camera_driver",
            "scout_motion_bridge",
            "scout_odom_bridge",
        ],
        "launch/companion_runtime.launch": ["companion_runtime_agent"],
        "launch/navigation.launch": ["map_file_guard", "map_server", "amcl", "move_base"],
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

    navigation_text = (REPO_ROOT / "launch" / "navigation.launch").read_text(encoding="utf-8")
    if 'name="odom_model_type"' not in navigation_text or "AUTO_SCOUT_ODOM_MODEL_TYPE" not in navigation_text:
        launch_issues.append("launch/navigation.launch must expose odom_model_type from AUTO_SCOUT_ODOM_MODEL_TYPE")
    if 'name="odom_alpha5"' not in navigation_text:
        launch_issues.append("launch/navigation.launch must set odom_alpha5 for omni motion support")

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

    container_issues = []
    compose_path = REPO_ROOT / "container" / "docker-compose.yml"
    dockerfile_path = REPO_ROOT / "container" / "Dockerfile"
    compose_text = compose_path.read_text(encoding="utf-8") if compose_path.is_file() else ""
    if compose_path.is_file():
        compose_config = load_yaml(compose_path)
        services = compose_config.get("services", {}) if isinstance(compose_config, dict) else {}
        if set(services.keys()) != {"companion-runtime"}:
            container_issues.append(
                "container/docker-compose.yml must define only the companion-runtime service"
            )

        service = services.get("companion-runtime", {})
        if not isinstance(service, dict):
            container_issues.append("companion-runtime service must be a mapping")
        else:
            if service.get("network_mode") != "host":
                container_issues.append("companion-runtime must use network_mode: host")
            if service.get("container_name") != "auto-scout-melodic":
                container_issues.append("companion-runtime must use the auto-scout-melodic container name")

            env = service.get("environment", {})
            if not isinstance(env, dict):
                container_issues.append("companion-runtime environment must be a mapping")
            elif env.get("AUTO_SCOUT_SITE_CONFIG") != "${AUTO_SCOUT_SITE_CONFIG}":
                container_issues.append(
                    "companion-runtime must forward AUTO_SCOUT_SITE_CONFIG into the container"
                )
            elif env.get("ROS_MASTER_URI") != "${AUTO_SCOUT_ROS_MASTER_URI}":
                container_issues.append("companion-runtime must source ROS_MASTER_URI from AUTO_SCOUT_ROS_MASTER_URI")
            elif env.get("ROS_HOSTNAME") != "${AUTO_SCOUT_ROS_HOSTNAME}":
                container_issues.append("companion-runtime must source ROS_HOSTNAME from AUTO_SCOUT_ROS_HOSTNAME")
            elif env.get("AUTO_SCOUT_ODOM_MODEL_TYPE") != "${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}":
                container_issues.append(
                    "companion-runtime must expose AUTO_SCOUT_ODOM_MODEL_TYPE with a diff-safe default"
                )

        if "roslaunch auto-scout companion_runtime.launch" not in compose_text:
            container_issues.append("companion-runtime command must launch auto-scout companion_runtime.launch")
        if "/opt/ros/melodic/setup.bash" not in compose_text:
            container_issues.append("companion-runtime command must source /opt/ros/melodic/setup.bash")
        if "localization_mode:=${AUTO_SCOUT_LOCALIZATION_MODE:-false}" not in compose_text:
            container_issues.append("companion-runtime must default localization_mode from AUTO_SCOUT_LOCALIZATION_MODE")
        if "site_file:=${AUTO_SCOUT_SITE_CONFIG}" not in compose_text:
            container_issues.append("companion-runtime must launch with AUTO_SCOUT_SITE_CONFIG")
        if "AUTO_SCOUT_ODOM_MODEL_TYPE" not in compose_text:
            container_issues.append("companion-runtime must pass AUTO_SCOUT_ODOM_MODEL_TYPE into the container")

    companion_start_path = REPO_ROOT / "scripts" / "start_companion_stack.sh"
    if companion_start_path.is_file():
        companion_start_text = companion_start_path.read_text(encoding="utf-8")
        if 'require_env AUTO_SCOUT_ROS_MASTER_URI' not in companion_start_text:
            container_issues.append("scripts/start_companion_stack.sh must fail fast when AUTO_SCOUT_ROS_MASTER_URI is unset")
        if 'require_env AUTO_SCOUT_ROS_HOSTNAME' not in companion_start_text:
            container_issues.append("scripts/start_companion_stack.sh must fail fast when AUTO_SCOUT_ROS_HOSTNAME is unset")
        if 'AUTO_SCOUT_LOCALIZATION_MODE="${AUTO_SCOUT_LOCALIZATION_MODE:-false}"' not in companion_start_text:
            container_issues.append("scripts/start_companion_stack.sh must export AUTO_SCOUT_LOCALIZATION_MODE with a mapping-safe default")
        if 'AUTO_SCOUT_ODOM_MODEL_TYPE="${AUTO_SCOUT_ODOM_MODEL_TYPE:-diff}"' not in companion_start_text:
            container_issues.append("scripts/start_companion_stack.sh must export AUTO_SCOUT_ODOM_MODEL_TYPE with a diff-safe default")
        if 'AUTO_SCOUT_ROS_MASTER_URI="${AUTO_SCOUT_ROS_MASTER_URI:-http://moorebot-scout.local:11311}"' in companion_start_text:
            container_issues.append("scripts/start_companion_stack.sh must not silently default ROS master settings to moorebot-scout.local")

    env_example_path = REPO_ROOT / "container" / ".env.example"
    if env_example_path.is_file():
        env_example_text = env_example_path.read_text(encoding="utf-8")
        if "AUTO_SCOUT_ODOM_MODEL_TYPE=diff" not in env_example_text:
            container_issues.append("container/.env.example must document AUTO_SCOUT_ODOM_MODEL_TYPE=diff")

    if dockerfile_path.is_file():
        dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
        required_dockerfile_strings = [
            "ENV ROS_DISTRO=melodic",
            "ros-melodic-ros-base",
            "ros-melodic-gmapping",
            "ros-melodic-move-base",
            "ros-melodic-explore-lite",
            "python-rosdep",
            "rosdep init || true && rosdep update",
        ]
        for item in required_dockerfile_strings:
            if item not in dockerfile_text:
                container_issues.append("container/Dockerfile missing '{}'".format(item))

    if container_issues:
        report.add(
            "repo.companion_container_contract",
            "fail",
            "Companion container does not match the supported single-container ROS1 design",
            details=container_issues,
        )
    else:
        report.add(
            "repo.companion_container_contract",
            "pass",
            "Companion stack stays inside one host-networked ROS1 container",
        )

    deploy_issues = []
    deploy_path = REPO_ROOT / "src" / "auto_scout" / "deploy.py"
    deploy_text = deploy_path.read_text(encoding="utf-8") if deploy_path.is_file() else ""
    if not deploy_path.is_file():
        deploy_issues.append("src/auto_scout/deploy.py is missing")
    else:
        if "moorebot-scout.local" in deploy_text:
            deploy_issues.append("src/auto_scout/deploy.py must not silently default ROS endpoints to moorebot-scout.local")
        if ".get(\"advertise_host\", \"localhost\")" in deploy_text:
            deploy_issues.append("src/auto_scout/deploy.py must not silently default ROS advertise_host to localhost")
        if "_require_configured_setting" not in deploy_text:
            deploy_issues.append("src/auto_scout/deploy.py must fail fast when ROS endpoint settings are absent")
        if "AUTO_SCOUT_ODOM_MODEL_TYPE" not in deploy_text:
            deploy_issues.append("src/auto_scout/deploy.py must render AUTO_SCOUT_ODOM_MODEL_TYPE for companion-runtime")

    if deploy_issues:
        report.add(
            "repo.deploy_contract",
            "fail",
            "Deploy rendering still contains unsupported fallback behavior",
            details=deploy_issues,
        )
    else:
        report.add(
            "repo.deploy_contract",
            "pass",
            "Deploy rendering fails fast on missing ROS endpoints and carries the Scout drive model",
        )

    build_issues = []
    cmake_path = REPO_ROOT / "CMakeLists.txt"
    cmake_text = cmake_path.read_text(encoding="utf-8") if cmake_path.is_file() else ""
    native_sources = [
        path for path in REPO_ROOT.rglob("*")
        if path.suffix.lower() in NATIVE_SOURCE_SUFFIXES
        and not any(
            item in path.parts
            for item in [".git", "legacy", "build", "devel", "install", "artifacts", "venv", ".venv"]
        )
    ]
    native_opencv_users = [path for path in native_sources if _native_source_uses_opencv(path)]
    if "find_package(OpenCV" in cmake_text and not native_opencv_users:
        build_issues.append("CMakeLists.txt must not require OpenCV when no native source files use it")
    if "${OpenCV_INCLUDE_DIRS}" in cmake_text and not native_opencv_users:
        build_issues.append("CMakeLists.txt must not inject OpenCV include dirs without native OpenCV consumers")

    if build_issues:
        report.add(
            "repo.build_dependency_contract",
            "fail",
            "Build metadata still carries an unsupported OpenCV dependency",
            details=build_issues,
            evidence={"native_sources": [str(path.relative_to(REPO_ROOT)) for path in native_sources]},
        )
    else:
        report.add(
            "repo.build_dependency_contract",
            "pass",
            "Build metadata does not require unused native OpenCV dependencies",
            evidence={"native_sources": [str(path.relative_to(REPO_ROOT)) for path in native_sources]},
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
            continue
        ssh_host = role.get("ssh", {}).get("host")
        if not ssh_host:
            issues.append("{} missing ssh.host".format(role_name))
        elif _is_generated_placeholder(ssh_host):
            issues.append("{} ssh.host still uses generated placeholder '{}'".format(role_name, ssh_host))

    if issues:
        report.add(
            "runtime.site_contract",
            "fail",
            "Selected role is not fully described in the site inventory",
            details=issues,
            evidence={"site_path": site_path},
        )
    else:
        report.add(
            "runtime.site_contract",
            "pass",
            "The site inventory describes the selected runtime role(s)",
            evidence={"site_path": site_path},
        )


def _add_remote_connectivity_check(report, site_config, effective_role, connectivity_check_enabled):
    roles_to_check = ["scout", "companion"] if effective_role == "system" else [effective_role]
    if not connectivity_check_enabled:
        report.add(
            "runtime.remote_connectivity",
            "skip",
            "Remote connectivity validation is disabled",
        )
        return

    payload = validate_site_connectivity(site_config, roles_to_check)
    if payload.get("ok", False):
        report.add(
            "runtime.remote_connectivity",
            "pass",
            "Configured SSH and ROS endpoints resolved and were reachable",
            evidence={"roles": payload.get("roles", {})},
        )
        return

    report.add(
        "runtime.remote_connectivity",
        "fail",
        "Configured SSH and ROS endpoints were not all reachable",
        details=payload.get("errors", []),
        evidence={"roles": payload.get("roles", {})},
    )


def _probe_mismatch_items(probe_result, prefixes):
    suggestions = probe_result.get("config_mismatch_suggestions", [])
    return [item for item in suggestions if any(item.get("path", "").startswith(prefix) for prefix in prefixes)]


def _add_live_probe_check(report, site_config, effective_role, runtime_profile, observe_motion, exercise_cmd_vel, live_probe_enabled):
    if effective_role not in ["scout", "system"]:
        report.add(
            "runtime.live_probe",
            "skip",
            "Live Scout probing is not required for the selected role",
        )
        return

    if not live_probe_enabled:
        report.add(
            "runtime.live_probe",
            "skip",
            "Live Scout probing is disabled",
        )
        return

    force_remote = runtime_profile != "likely_scout"
    probe_result = probe_scout_capabilities(
        site_config,
        observe_motion_seconds=observe_motion,
        exercise_cmd_vel=exercise_cmd_vel,
        force_remote=force_remote,
    )
    if not probe_result.get("ok", False):
        report.add(
            "runtime.live_probe",
            "warn",
            "Live Scout probe was unavailable; falling back to declarative validation",
            details=probe_result.get("errors", []),
            evidence={"probe": probe_result},
        )
        return

    mismatch_items = _probe_mismatch_items(
        probe_result,
        [
            "roles.scout.capabilities.pose",
            "roles.scout.capabilities.motion",
            "roles.scout.devices.lidar",
            "roles.scout.topics.odom",
            "roles.scout.topics.vendor_cmd_vel",
            "roles.scout.ros.master_uri",
            "roles.scout.ros.advertise_host",
        ],
    )
    details = []
    observed_motion = probe_result.get("observed", {}).get("motion_observation")
    if observe_motion and observed_motion and not observed_motion.get("moved", False):
        details.append("Observed odometry did not change during the motion observation window.")
    elif observe_motion and observed_motion:
        details.append(
            "Observed odometry changed during the motion observation window "
            "(dx={:.3f}, dy={:.3f}, dominant_axis={}).".format(
                observed_motion.get("delta_x", 0.0),
                observed_motion.get("delta_y", 0.0),
                observed_motion.get("dominant_axis", "none"),
            )
        )
    elif not observe_motion:
        details.append("Pose was not dynamically confirmed; rerun with --observe-motion to verify movement.")

    command_exercise = probe_result.get("observed", {}).get("command_exercise", {})
    if exercise_cmd_vel and not command_exercise.get("moved", False):
        details.append("Vendor command exercise did not produce observable motion.")
    elif exercise_cmd_vel:
        details.append(
            "Vendor command exercise produced observable motion "
            "(forward_axis={}, dx={:.3f}, dy={:.3f}, dominant_axis={}).".format(
                command_exercise.get("forward_axis"),
                command_exercise.get("delta_x", 0.0),
                command_exercise.get("delta_y", 0.0),
                command_exercise.get("dominant_axis", "none"),
            )
        )

    if mismatch_items:
        details.extend(
            "{} -> {} ({})".format(item["path"], item.get("suggested"), item.get("reason"))
            for item in mismatch_items
        )
        report.add(
            "runtime.live_probe",
            "fail",
            "Live Scout probe contradicts the declared Scout interface or capabilities",
            details=details,
            evidence={"probe": probe_result},
        )
        return

    report.add(
        "runtime.live_probe",
        "pass" if observe_motion else "warn",
        "Live Scout probe matched the declared Scout interface" if observe_motion else "Live Scout probe matched configured topics, but pose was not dynamically confirmed",
        details=details,
        evidence={"probe": probe_result},
    )


def _add_scout_serial_access_check(report, site_config, runtime_profile, live_probe_enabled):
    scout = role_config(site_config, "scout")
    lidar_path = scout.get("devices", {}).get("lidar")
    service_user, service_group = role_service_identity(scout)

    if not live_probe_enabled:
        report.add(
            "runtime.scout_serial_access",
            "skip",
            "Scout serial-access probing is disabled",
            evidence={"service_user": service_user, "service_group": service_group},
        )
        return

    executor = ProbeExecutor(scout, force_remote=runtime_profile != "likely_scout")

    if not lidar_path:
        report.add(
            "runtime.scout_serial_access",
            "fail",
            "Scout lidar device is not configured",
            details=["roles.scout.devices.lidar must be set before Scout LiDAR validation can pass."],
        )
        return

    exists_result = executor.run(
        "test -e {} && echo present || echo missing".format(shlex.quote(lidar_path)),
        check=False,
    )
    if not exists_result.ok or "present" not in exists_result.stdout:
        report.add(
            "runtime.scout_serial_access",
            "fail",
            "Configured Scout lidar device is missing",
            details=["Configured lidar device not found: {}".format(lidar_path)],
            evidence={"service_user": service_user, "service_group": service_group},
        )
        return

    stat_result = executor.run(
        "stat -c '%a %U %G' {}".format(shlex.quote(lidar_path)),
        check=False,
    )
    groups_result = executor.run(
        "id -nG {}".format(shlex.quote(service_user)),
        check=False,
    )
    if not stat_result.ok or not groups_result.ok:
        details = []
        if not stat_result.ok:
            details.append("Could not inspect {} permissions.".format(lidar_path))
        if not groups_result.ok:
            details.append("Could not inspect groups for service user '{}'.".format(service_user))
        report.add(
            "runtime.scout_serial_access",
            "warn",
            "Scout lidar device exists, but serial-access validation was incomplete",
            details=details,
            evidence={"service_user": service_user, "service_group": service_group},
        )
        return

    stat_fields = (stat_result.stdout or "").strip().split()
    if len(stat_fields) < 3:
        report.add(
            "runtime.scout_serial_access",
            "warn",
            "Scout lidar device exists, but permission output could not be parsed",
            details=["Unexpected stat output for {}: {}".format(lidar_path, stat_result.stdout.strip())],
            evidence={"service_user": service_user, "service_group": service_group},
        )
        return

    mode_text, owner, group = stat_fields[:3]
    service_groups = [item for item in (groups_result.stdout or "").strip().split() if item]
    if _service_user_has_device_access(mode_text, owner, group, service_user, service_groups):
        report.add(
            "runtime.scout_serial_access",
            "pass",
            "Scout service user can access the configured LiDAR serial device",
            details=[
                "Device: {} (mode {}, owner {}, group {})".format(lidar_path, mode_text, owner, group),
                "Service user '{}' groups: {}".format(service_user, ", ".join(service_groups) or "none"),
            ],
        )
        return

    details = [
        "Device: {} (mode {}, owner {}, group {})".format(lidar_path, mode_text, owner, group),
        "Service user '{}' groups: {}".format(service_user, ", ".join(service_groups) or "none"),
    ]
    if group == "dialout" and "dialout" not in service_groups:
        details.append("Service user '{}' is not in the 'dialout' group.".format(service_user))
    elif group and group not in service_groups and owner != service_user:
        details.append("Service user '{}' is not in the device group '{}'.".format(service_user, group))

    report.add(
        "runtime.scout_serial_access",
        "fail",
        "Scout service user cannot access the configured LiDAR serial device",
        details=details,
        evidence={"service_user": service_user, "service_group": service_group},
    )


def _add_scout_checks(report, site_config, runtime_profile):
    scout = role_config(site_config, "scout")
    capabilities = scout.get("capabilities", {})
    devices = scout.get("devices", {})
    topics = scout.get("topics", {})
    ros_settings = scout.get("ros", {})

    issues = []
    if not capabilities.get("vendor_bridge", False):
        issues.append("scout.capabilities.vendor_bridge must be true")
    if not capabilities.get("camera", False):
        issues.append("scout.capabilities.camera must be true")
    if not capabilities.get("scan", False):
        issues.append("scout.capabilities.scan must be true")
    if not capabilities.get("motion", False):
        issues.append("scout.capabilities.motion must be true")

    for name in ["camera", "lidar"]:
        if name not in devices:
            issues.append("scout.devices.{} is missing".format(name))
    for name in ["odom", "vendor_cmd_vel", "autonomy_cmd_vel"]:
        if name not in topics:
            issues.append("scout.topics.{} is missing".format(name))
    if not ros_settings.get("advertise_host"):
        issues.append("scout.ros.advertise_host is missing")
    elif _is_generated_placeholder(ros_settings.get("advertise_host")):
        issues.append("scout.ros.advertise_host still uses a generated placeholder")
    try:
        normalize_drive_model(role_motion_setting(scout, "drive_model"))
    except ValueError as exc:
        issues.append(str(exc))

    status = "fail" if issues else "pass"
    summary = "Scout inventory declares the required bridge, motion, camera, and scan capabilities"
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
            "topics": topics,
            "ros": ros_settings,
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
    if not ros_settings.get("master_uri"):
        issues.append("companion.ros.master_uri is missing")
    elif _is_generated_placeholder(ros_settings.get("master_uri")):
        issues.append("companion.ros.master_uri still uses a generated placeholder")
    if not ros_settings.get("advertise_host"):
        issues.append("companion.ros.advertise_host is missing")
    elif _is_generated_placeholder(ros_settings.get("advertise_host")):
        issues.append("companion.ros.advertise_host still uses a generated placeholder")
    if ros_settings.get("master_uri", "").startswith("http://localhost"):
        issues.append("companion.ros.master_uri must not point to localhost in the cross-host topology")

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


def _add_pose_gate_check(report, site_config):
    declared_sources = []
    for role_name in ["scout", "companion"]:
        if role_config(site_config, role_name).get("capabilities", {}).get("pose", False):
            declared_sources.append(role_name)

    if declared_sources:
        report.add(
            "runtime.pose_gate",
            "pass",
            "A pose source is declared for mapping and patrol",
            details=["Declared pose provider(s): {}".format(", ".join(declared_sources))],
        )
        return

    report.add(
        "runtime.pose_gate",
        "fail",
        "Pose remains the primary integration blocker for mapping and patrol",
        details=[
            "Neither roles.scout.capabilities.pose nor roles.companion.capabilities.pose is enabled.",
            "Prove odometry or another pose source before treating navigation-stack changes as the next step.",
        ],
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
    system_caps = {
        name: gate["capabilities"].get(name, False)
        for name in ["scan", "pose", "motion", "camera"]
    }
    companion = role_config(site_config, "companion")
    if not system_caps.get("scan", False):
        mapping_issues.append("Scout scan capability is disabled")
    if not system_caps.get("pose", False):
        mapping_issues.append("System pose capability is disabled")
    if not companion.get("storage", {}).get("maps_dir"):
        mapping_issues.append("Companion maps_dir is missing")

    patrol_issues = []
    if not system_caps.get("pose", False):
        patrol_issues.append("Pose capability is required for localization and patrol")
    if not system_caps.get("camera", False):
        patrol_issues.append("Camera capability is required for patrol proof capture")
    if not system_caps.get("motion", False):
        patrol_issues.append("Motion capability is required for autonomous patrol")

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


def add_runtime_checks(
    report,
    site_config,
    site_path,
    effective_role,
    runtime_profile,
    live_probe_enabled=True,
    observe_motion=0.0,
    exercise_cmd_vel=False,
    connectivity_check_enabled=True,
):
    """Validate local/runtime readiness for the selected role."""
    _add_identity_check(report, effective_role, runtime_profile)
    _add_site_role_checks(report, site_config, site_path, effective_role)
    _add_remote_connectivity_check(report, site_config, effective_role, connectivity_check_enabled)
    _add_resource_check(report)

    if effective_role in ["scout", "system"]:
        _add_scout_checks(report, site_config, runtime_profile)
        _add_scout_serial_access_check(report, site_config, runtime_profile, live_probe_enabled)

    if effective_role in ["companion", "system"]:
        _add_companion_checks(report, site_config, runtime_profile)

    _add_live_probe_check(
        report,
        site_config,
        effective_role,
        runtime_profile,
        observe_motion,
        exercise_cmd_vel,
        live_probe_enabled,
    )
    _add_pose_gate_check(report, site_config)
    _add_mission_checks(report, site_config)


def build_parser():
    parser = argparse.ArgumentParser(description="Validate Auto-Scout repo and runtime assumptions")
    parser.add_argument("--mode", choices=["repo", "runtime", "all"], default="all")
    parser.add_argument("--role", choices=["auto", "scout", "companion", "system"], default="auto")
    parser.add_argument("--site", default=None)
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "scout_config.yaml"))
    parser.add_argument("--no-live-probe", action="store_true", help="Disable live Scout probing")
    parser.add_argument("--skip-connectivity-check", action="store_true", help="Skip remote connectivity validation")
    parser.add_argument("--observe-motion", type=float, default=0.0, help="Observe odometry while manually driving the Scout")
    parser.add_argument("--exercise-cmd-vel", action="store_true", help="Publish a short command on the vendor motion topic during probing")
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
        add_runtime_checks(
            report,
            site_config,
            site_path,
            effective_role,
            runtime_profile,
            live_probe_enabled=not args.no_live_probe,
            observe_motion=args.observe_motion,
            exercise_cmd_vel=args.exercise_cmd_vel,
            connectivity_check_enabled=not args.skip_connectivity_check,
        )

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

#!/usr/bin/env python3
"""Regenerate the repository directory listing block in README.md.

The listing drifts every time a file is added, so generate it instead of
hand-maintaining it. Descriptions live in DESCRIPTIONS below and are keyed by
repo-relative path; anything without an entry is emitted with a TODO marker so
new files are visibly undocumented rather than silently missing.

Usage:
    tools/generate_readme_tree.py            # rewrite README.md in place
    tools/generate_readme_tree.py --check    # exit 1 if README.md is stale
"""

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
BEGIN_MARKER = "```text"
END_MARKER = "```"
SECTION_HEADING = "## Repository Directory Listing"

# Paths that are generated locally and gitignored, but that operators still see
# in a working checkout. Rendered after the tracked tree.
UNTRACKED_NOTES = [
    ("artifacts/", "Local artifact root created by CLI runs; ignored by git."),
    ("artifacts/runs/", "Timestamped configure, deploy, validate, and mission output directories."),
    ("config/site_local.yaml", "Untracked local inventory written by the configure flow."),
    ("data/", "Placeholder for local maps, calibration data, or samples; empty in git."),
    ("templates/", "Placeholder for local or legacy template assets; empty in git."),
    ("validation-report.json", "Local validator JSON output; generated and ignored by git."),
]

DESCRIPTIONS = {
    ".gitignore": "Ignore Python, ROS, build, media, and local override artifacts.",
    "CHANGELOG.md": "Historical changelog; older entries reflect pre-reset functionality.",
    "CMakeLists.txt": "Catkin build/install definition for ROS launch files, configs, docs, and Python nodes.",
    "CONTRIBUTING.md": "Contributor guidance aligned with the companion-first reset.",
    "LICENSE": "MIT license for the repository.",
    "README.md": "Primary project overview, architecture notes, and operator guidance.",
    "auto-scout": "Repo-local Python entrypoint for the headless CLI.",
    "check_scout_compatibility.py": "Canonical validator for repo contracts, runtime assumptions, and mission readiness.",
    "package.xml": "ROS package manifest and dependency declaration.",
    "requirements.txt": "Python dependency list for runtime, validation, and tests.",
    "setup.py": "Python packaging metadata and console-script entrypoint definition.",
    "config": "Runtime, inventory, mission, and navigation parameter files.",
    "config/base_local_planner_params.yaml": "TrajectoryPlannerROS tuning for local path execution.",
    "config/costmap_common_params.yaml": "Shared obstacle, footprint, and laser source settings for costmaps.",
    "config/global_costmap_params.yaml": "Global costmap frame and update settings.",
    "config/global_planner_params.yaml": "GlobalPlanner behavior and cost tuning.",
    "config/local_costmap_params.yaml": "Local rolling-window costmap configuration.",
    "config/scout_config.yaml": "Main runtime config covering topics, storage, waypoints, safety, and navigation defaults.",
    "config/site.yaml": "Tracked sample inventory for Scout and companion roles.",
    "config/missions": "Mission definitions invoked through the CLI.",
    "config/missions/smoke_loop.yaml": "Proof mission that loops rooms, returns, captures media, and notifies.",
    "container": "Companion container build and compose assets.",
    "container/.env.example": "Example environment variables for direct Docker Compose usage.",
    "container/Dockerfile": "Ubuntu 18.04 plus ROS Melodic container image for the companion runtime.",
    "container/docker-compose.yml": "Host-networked companion stack definition and launch command.",
    "container/entrypoint.sh": "Small container entrypoint that sources ROS and execs the requested command.",
    "docs": "Supporting architecture, setup, quick-start, and validation guides.",
    "docs/AUTO_SCOUT_CHECKLIST.md": "Current hardware, deployment, validation, and mapping checklist.",
    "docs/BRINGUP_ROADMAP.md": "Staged plan for validating the device from code fixes through missions.",
    "docs/CODE_REVIEW_2026-08.md": "August 2026 review findings covering bugs, security, and doc accuracy.",
    "docs/LOGGING_ALERTING_RUNBOOK.md": "Logs, warnings, Slack alerts, and retention reference for troubleshooting.",
    "docs/QUICKSTART.md": "Short path to probe, deploy, map, and validate the supported stack.",
    "docs/ROCKCHIP_SERVICE_FINDINGS.md": "Findings on the vendor rockchip service and Scout boot behavior.",
    "docs/VALIDATION.md": "Detailed validator modes, checks, and failure interpretation.",
    "docs/VERIFIED_ARCHITECTURE.md": "Verified hardware/software facts and the design conclusions derived from them.",
    "docs/setup_guide.md": "End-to-end Moorebot Scout plus LD19 companion setup guide.",
    "hardware": "Physical mounting and fixture assets.",
    "hardware/lidar_harness": "Parametric LD19 harness model and measurement worksheet.",
    "hardware/lidar_harness/README.md": "Measurement worksheet, print settings, and post-install steps.",
    "hardware/lidar_harness/scout_ld19_harness.scad": "Parametric OpenSCAD harness; all hardware dimensions are unverified placeholders.",
    "launch": "ROS launch entrypoints for Scout and companion roles.",
    "launch/companion_runtime.launch": "Starts companion heartbeat and lazy vendor JPG camera bridge; gates nav/map-return behind enable_nav_stack.",
    "launch/navigation.launch": "Companion localization plus `move_base` stack for saved-map patrols.",
    "launch/scout_complete.launch": "Combined bring-up wrapper for optional local Scout bridge plus companion runtime.",
    "launch/scout_runtime.launch": "Scout-side runtime launch with optional isolated lidar/camera and feature-gated core process.",
    "launch/slam_mapping.launch": "Companion-side gmapping stack with robot model and transforms.",
    "legacy": "Quarantined browser and voice surfaces that are no longer on the supported path.",
    "legacy/README.md": "Explains what was retired and where the supported interfaces now live.",
    "legacy/dashboard.html": "Old browser dashboard UI asset kept for reference only.",
    "legacy/scout-web.service": "Legacy systemd unit for the retired web interface.",
    "legacy/scout_web_interface_legacy.py": "Archived Flask and Socket.IO dashboard implementation.",
    "legacy/voice_command_interface_legacy.py": "Archived speech-recognition control surface.",
    "rviz": "RViz visualization presets.",
    "rviz/scout_navigation.rviz": "RViz workspace for scan, map, robot model, and path visualization.",
    "scripts": "Shell entrypoints used by rendered systemd services.",
    "scripts/cleanup_ros_logs.py": "Bounds ROS log directories by age and total file size.",
    "scripts/collect_scout_resource_metrics.sh": "Captures Scout load, memory, swap, disk, and process snapshots.",
    "scripts/provision_pi_known_hosts.sh": "Populates Pi-side SSH known hosts without disabling host-key checking.",
    "scripts/start_companion_stack.sh": "Starts or stops the companion Docker Compose stack.",
    "scripts/start_scout_runtime.sh": "Sources ROS/catkin state and launches the Scout runtime.",
    "src": "Python source tree for CLI, runtime nodes, and helpers.",
    "src/__init__.py": "Top-level package metadata.",
    "src/battery_map_return_controller.py": "Companion node that can claim low-battery map return and drive to the dock approach waypoint.",
    "src/companion_notifications.py": "Python 2 Slack payload builders shared by companion mission reporting.",
    "src/companion_runtime_agent.py": "Python 2 Scout-compatible companion heartbeat publisher.",
    "src/companion_runtime_support.py": "Python 2 helper functions shared by companion ROS scripts.",
    "src/config_utils.py": "Thin compatibility wrapper around Scout config loading helpers.",
    "src/dog_detection_module.py": "External dog-detection event bridge that persists companion-side events.",
    "src/ld19_lidar_driver.py": "ROS driver that reads LD19 packets and publishes `sensor_msgs/LaserScan`.",
    "src/ld19_protocol.py": "Reusable LD19 packet parsing, CRC validation, and scan assembly helpers.",
    "src/map_file_guard.py": "Fails localization launch early when the configured map file is missing.",
    "src/scout_battery_dock_guard.py": "Scout-local low-battery guard and vendor `/nav_low_bat` docking handoff.",
    "src/scout_camera_driver.py": "Opt-in direct `/dev/video0` compressed-image camera fallback for the Scout runtime.",
    "src/scout_core_runtime.py": "Consolidated Scout-side heartbeat, bridge, guard, safety, odom, and motion runtime.",
    "src/scout_imu_bridge.py": "Normalize the vendor IMU topic to `/scout/imu/data`.",
    "src/scout_motion_bridge.py": "Republish standard autonomy `Twist` commands onto the vendor motion topic.",
    "src/scout_navigation_controller.py": "Python 2 companion-side smoke-loop mission runner.",
    "src/scout_node_utils.py": "Shared helpers for standalone and consolidated Scout node setup.",
    "src/scout_odom_bridge.py": "Normalize vendor odometry into `/odom` plus TF.",
    "src/scout_runtime_agent.py": "Python 2 Scout runtime heartbeat publisher.",
    "src/scout_runtime_config.py": "Python 2-safe site/config loader for Scout-launched nodes.",
    "src/scout_safety_filter.py": "Gate planner velocity commands using ToF, LiDAR heartbeat, and battery guard state.",
    "src/scout_tof_bridge.py": "Normalize the vendor ToF range topic to `/scout/tof`.",
    "src/scout_web_interface.py": "Explicit stub that exits and points users at the retired legacy dashboard.",
    "src/vendor_jpg_bridge.py": "Companion adapter from vendor `/CoreNode/jpg` frames to standard compressed images.",
    "src/voice_command_interface.py": "Explicit stub that exits and points users at the retired legacy voice path.",
    "src/auto_scout": "Python 3 package for the clean-slate CLI and shared runtime logic.",
    "src/auto_scout/__init__.py": "Package version marker for the clean-slate runtime.",
    "src/auto_scout/artifacts.py": "Helpers for writing timestamped artifact logs and JSON outputs.",
    "src/auto_scout/cli.py": "Argument parser and command dispatcher for configure, deploy, validate, probe, and run.",
    "src/auto_scout/command_runner.py": "Local, SSH, rsync, and SCP command execution helpers with dry-run support.",
    "src/auto_scout/deploy.py": "Scout and companion deployment routines plus rendered systemd service templates.",
    "src/auto_scout/install_config.py": "Interactive and flag-driven install/deploy configuration helpers.",
    "src/auto_scout/live_probe.py": "Live Scout topic/device probing and site-inventory reconciliation logic.",
    "src/auto_scout/mission_config.py": "Mission path resolution and YAML loading helpers.",
    "src/auto_scout/mission_runner.py": "Mission gating and remote smoke-loop invocation helpers.",
    "src/auto_scout/network_validation.py": "DNS, TCP, and SSH reachability validation for configured hosts.",
    "src/auto_scout/notifications.py": "Slack payload builders for mission, preflight, and resource alerts.",
    "src/auto_scout/paths.py": "Common repository path constants.",
    "src/auto_scout/redaction.py": "Strips webhook URLs and other secrets from reports and artifacts.",
    "src/auto_scout/resource_alerts.py": "Scout/Pi critical resource alert collection and cooldown logic.",
    "src/auto_scout/site_config.py": "Site inventory defaults, read/write helpers, and role-specific accessors.",
    "src/auto_scout/yaml_loader.py": "YAML load/dump helpers with repo-local fallback parsing.",
    "src/auto_scout/runtime": "Python 3 runtime-side helpers that mirror the Python 2 agents/controllers.",
    "src/auto_scout/runtime/__init__.py": "Runtime helper package marker.",
    "src/auto_scout/runtime/heartbeat.py": "Role-aware Python 3 heartbeat publisher for Scout or companion.",
    "src/auto_scout/runtime/mission_controller.py": "Lean Python 3 companion smoke mission controller implementation.",
    "systemd": "Example service units; deploy renders role-specific variants from code.",
    "systemd/auto-scout-companion-resource-alert.service": "Example companion critical resource alert unit.",
    "systemd/auto-scout-companion-resource-alert.timer": "Example timer for periodic companion resource alerts.",
    "systemd/auto-scout-companion-runtime.service": "Example companion systemd unit.",
    "systemd/auto-scout-ros-log-cleanup.service": "Example ROS log retention cleanup unit.",
    "systemd/auto-scout-ros-log-cleanup.timer": "Example timer for daily ROS log cleanup.",
    "systemd/auto-scout-scout-resource-metrics.service": "Example Scout resource metrics collection unit.",
    "systemd/auto-scout-scout-resource-metrics.timer": "Example timer for periodic Scout resource metrics.",
    "systemd/auto-scout-scout-runtime.service": "Example Scout systemd unit.",
    "systemd/auto-scout-scout-swap-setup.service": "Example one-shot setup unit for persistent Scout swap.",
    "systemd/userdata-auto\\x2dscout-auto\\x2dscout.swap.swap": "Example systemd swap unit for /userdata/auto-scout/auto-scout.swap.",
    "tests": "Regression coverage for validator, probing, runtime, and protocol behavior.",
    "tests/__init__.py": "Test package marker.",
    "tests/test_battery_map_return_controller.py": "Unit tests for companion map-return claim eligibility.",
    "tests/test_clock_skew_check.py": "Unit tests for the Scout/companion clock skew validator check.",
    "tests/test_companion_notifications.py": "Unit tests for companion Slack payload construction.",
    "tests/test_ld19_protocol.py": "Unit tests for LD19 packet parsing, CRC rejection, and scan assembly.",
    "tests/test_live_probe.py": "Unit tests for live Scout probing inference and config suggestions.",
    "tests/test_remote_access.py": "Unit tests for remote connectivity validation helpers.",
    "tests/test_resource_alerts.py": "Unit tests for resource alert thresholds and cooldown behavior.",
    "tests/test_ros_log_cleanup.py": "Unit tests for ROS log retention, size accounting, and pruning.",
    "tests/test_scout_battery_dock_guard.py": "Unit tests for the low-battery docking guard state machine.",
    "tests/test_scout_navigation_controller.py": "Unit tests for the companion smoke-loop mission controller.",
    "tests/test_scout_odom_bridge.py": "Unit tests for vendor odometry normalization and TF publishing.",
    "tests/test_scout_safety_filter.py": "Unit tests for ToF, scan, and battery-guard command-gating decisions.",
    "tests/test_scout_safety_filter_concurrency.py": "Lock-discipline and stress tests for the threaded safety filter node.",
    "tests/test_scout_sensor_bridges.py": "Unit tests for ToF and IMU vendor topic normalization.",
    "tests/test_site_config.py": "Unit tests for layered site inventory loading.",
    "tests/test_validation_cli.py": "End-to-end regression tests for the validator and CLI contracts.",
    "tests/test_vendor_jpg_bridge.py": "Unit tests for vendor JPG frame decoding and lazy subscription.",
    "tools": "Compatibility utilities and wrappers used by the runtime and operators.",
    "tools/deploy.sh": "Compatibility shell wrapper around `./auto-scout deploy`.",
    "tools/generate_readme_tree.py": "Regenerates the README repository directory listing.",
    "tools/yaml_fallback.py": "Minimal YAML parser used when PyYAML is unavailable.",
    "urdf": "Robot description assets.",
    "urdf/scout.urdf": "Minimal Scout robot model with base, lidar, camera, ToF, and IMU frames.",
}


def tracked_paths():
    """Return git-tracked repo-relative paths, so the listing matches the repo.

    NUL-separated: the swap unit filename contains backslashes, and plain
    `git ls-files` would wrap it in quotes and mangle the path split.
    """
    output = subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        text=True,
    )
    return sorted(item for item in output.split("\0") if item.strip())


def build_tree(paths):
    tree = {}
    for path in paths:
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})
    return tree


def describe(path, is_dir):
    description = DESCRIPTIONS.get(path)
    if description:
        return description
    return "TODO: describe this {}.".format("directory" if is_dir else "file")


def render(tree, prefix="", parent="", rows=None):
    """Collect (tree_text, description) rows; alignment happens in build_block."""
    if rows is None:
        rows = []
    entries = sorted(tree.items(), key=lambda item: (not bool(item[1]), item[0].lower()))
    for index, (name, children) in enumerate(entries):
        last = index == len(entries) - 1
        connector = "`--" if last else "|--"
        path = "{}/{}".format(parent, name) if parent else name
        label = "{}/".format(name) if children else name
        rows.append(("{}{} {}".format(prefix, connector, label), describe(path, bool(children))))
        if children:
            render(children, prefix + ("    " if last else "|   "), path, rows)
    return rows


def build_block():
    rows = render(build_tree(tracked_paths()))
    width = max(len(text) for text, _ in rows) if rows else 0

    lines = ["."]
    lines.extend("{}  # {}".format(text.ljust(width), description) for text, description in rows)
    lines.append("")
    lines.append("Generated local directories (gitignored, but present in a working checkout):")
    for path, description in UNTRACKED_NOTES:
        lines.append("  {:<36} # {}".format(path, description))
    return "\n".join(lines)


def replace_block(readme_text, block):
    if SECTION_HEADING not in readme_text:
        raise SystemExit("README.md is missing the '{}' heading".format(SECTION_HEADING))

    head, tail = readme_text.split(SECTION_HEADING, 1)
    start = tail.find(BEGIN_MARKER)
    if start == -1:
        raise SystemExit("README.md listing section has no opening code fence")
    end = tail.find("\n{}".format(END_MARKER), start + len(BEGIN_MARKER))
    if end == -1:
        raise SystemExit("README.md listing section has no closing code fence")

    rebuilt = "{}{}\n{}\n{}{}".format(
        tail[: start + len(BEGIN_MARKER)],
        "",
        block,
        END_MARKER,
        tail[end + len("\n{}".format(END_MARKER)) :],
    )
    return "{}{}{}".format(head, SECTION_HEADING, rebuilt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit non-zero if README.md is stale.")
    args = parser.parse_args(argv)

    current = README_PATH.read_text(encoding="utf-8")
    updated = replace_block(current, build_block())

    if args.check:
        if current != updated:
            print("README.md directory listing is stale; run tools/generate_readme_tree.py", file=sys.stderr)
            return 1
        print("README.md directory listing is current")
        return 0

    if current != updated:
        README_PATH.write_text(updated, encoding="utf-8")
        print("README.md directory listing updated")
    else:
        print("README.md directory listing already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Helpers for invoking named missions through the companion runtime."""

import os
import shlex

from auto_scout.command_runner import CommandRunner
from auto_scout.paths import DEFAULT_SCOUT_CONFIG
from auto_scout.site_config import role_config, system_capabilities


CONTAINER_WORKSPACE = "/opt/catkin_ws/src/auto-scout"


def evaluate_smoke_loop_gate(site_config, mission_config):
    """Return a structured preflight gate for the smoke loop mission."""
    issues = []
    capabilities = system_capabilities(site_config)
    required = mission_config.get("preconditions", {}).get("required_capabilities", [])

    for capability in required:
        if not capabilities.get(capability, False):
            issues.append("Missing declared capability '{}'".format(capability))

    return_config = mission_config.get("return", {})
    if return_config.get("mode") == "dock_if_available" and not capabilities.get("dock", False):
        if not return_config.get("fallback_waypoint"):
            issues.append("Docking is unavailable and no fallback waypoint is configured")

    notification = mission_config.get("notification", {})
    if notification.get("enabled", False) and not capabilities.get(notification.get("require_capability", "notify"), False):
        issues.append("Notification is required by the mission but notify capability is disabled")
    if notification.get("enabled", False):
        webhook_url = (
            site_config.get("roles", {}).get("companion", {}).get("notifications", {}).get("webhook_url")
            or ""
        )
        if not webhook_url:
            issues.append("Notification is required by the mission but companion.notifications.webhook_url is empty")

    return {
        "ok": not issues,
        "issues": issues,
        "capabilities": capabilities,
    }


def _build_smoke_loop_remote_command(companion, mission_path, artifact_run):
    """Return the remote command that runs the smoke loop inside the companion container."""
    ros_settings = companion.get("ros", {})
    container_name = ros_settings.get("container_name", "auto-scout-melodic")
    container_site = os.path.join(CONTAINER_WORKSPACE, "config", "site.yaml")
    container_config = os.path.join(CONTAINER_WORKSPACE, "config", os.path.basename(str(DEFAULT_SCOUT_CONFIG)))
    container_mission = os.path.join(CONTAINER_WORKSPACE, "config", "missions", os.path.basename(mission_path))
    container_artifact_dir = os.path.join(
        CONTAINER_WORKSPACE,
        "artifacts",
        "runs",
        os.path.basename(str(artifact_run.path)),
    )
    inner_command = (
        "source /opt/ros/melodic/setup.bash && "
        "if [ -f /opt/catkin_ws/devel/setup.bash ]; then source /opt/catkin_ws/devel/setup.bash; fi && "
        "cd {workspace} && "
        "AUTO_SCOUT_SITE_CONFIG={site} "
        "AUTO_SCOUT_CONFIG={config} "
        "python2 src/scout_navigation_controller.py "
        "--site {site} --config {config} --mission {mission} --artifact-dir {artifact}"
    ).format(
        workspace=shlex.quote(CONTAINER_WORKSPACE),
        site=shlex.quote(container_site),
        config=shlex.quote(container_config),
        mission=shlex.quote(container_mission),
        artifact=shlex.quote(container_artifact_dir),
    )
    return "docker exec {container} /bin/bash -lc {command}".format(
        container=shlex.quote(container_name),
        command=shlex.quote(inner_command),
    )


def run_smoke_loop(site_config, site_path, mission_config, mission_path, artifact_run, dry_run=False):
    """Invoke the smoke loop on the companion host."""
    gate = evaluate_smoke_loop_gate(site_config, mission_config)
    artifact_run.write_json("preflight-gate.json", gate)
    if not gate["ok"]:
        return {
            "ok": False,
            "phase": "preflight",
            "issues": gate["issues"],
        }

    companion = role_config(site_config, "companion")
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    remote_command = _build_smoke_loop_remote_command(companion, mission_path, artifact_run)
    runner.run_remote(companion["ssh"], remote_command)

    return {
        "ok": True,
        "phase": "remote_execution",
        "dry_run": dry_run,
        "site_path": site_path,
        "mission_path": mission_path,
        "host": companion["ssh"]["host"],
    }

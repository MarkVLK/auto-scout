"""Helpers for invoking named missions through the companion runtime."""

import os

from auto_scout.command_runner import CommandRunner
from auto_scout.paths import DEFAULT_SCOUT_CONFIG
from auto_scout.site_config import role_config, system_capabilities


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
    workspace_dir = companion["workspace_dir"]
    remote_site = os.path.join(workspace_dir, "config", "site.yaml")
    remote_config = os.path.join(workspace_dir, "config", os.path.basename(str(DEFAULT_SCOUT_CONFIG)))
    remote_mission = os.path.join(workspace_dir, "config", "missions", os.path.basename(mission_path))
    remote_artifact_dir = os.path.join(workspace_dir, str(artifact_run.path.relative_to(artifact_run.path.parents[2])))

    remote_command = (
        "cd '{workspace}' && "
        "AUTO_SCOUT_SITE_CONFIG='{site}' "
        "AUTO_SCOUT_CONFIG='{config}' "
        "python3 src/scout_navigation_controller.py "
        "--site '{site}' --config '{config}' --mission '{mission}' --artifact-dir '{artifact}'"
    ).format(
        workspace=workspace_dir,
        site=remote_site,
        config=remote_config,
        mission=remote_mission,
        artifact=remote_artifact_dir,
    )
    runner.run_remote(companion["ssh"], remote_command)

    return {
        "ok": True,
        "phase": "remote_execution",
        "dry_run": dry_run,
        "site_path": site_path,
        "mission_path": mission_path,
        "host": companion["ssh"]["host"],
    }

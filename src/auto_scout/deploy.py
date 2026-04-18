"""Deployment routines for the clean-slate Scout and companion runtimes."""

from auto_scout.command_runner import CommandRunner
from auto_scout.paths import repo_root
from auto_scout.site_config import role_config


SYNC_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "artifacts/runs",
]


def _service_install_commands(workspace_dir, service_name):
    service_path = "{}/systemd/{}".format(workspace_dir, service_name)
    return [
        "sudo cp '{}' '/etc/systemd/system/{}'".format(service_path, service_name),
        "sudo systemctl daemon-reload",
        "sudo systemctl enable {}".format(service_name),
        "sudo systemctl restart {}".format(service_name),
    ]


def deploy_scout(site_config, artifact_run, dry_run=False):
    """Sync the repo and install the Scout runtime service."""
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    scout = role_config(site_config, "scout")
    workspace_dir = scout["workspace_dir"]
    service_name = "auto-scout-scout-runtime.service"
    target_root = scout["ssh"]

    runner.run_remote(target_root, "mkdir -p '{}'".format(workspace_dir))
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    for command in _service_install_commands(workspace_dir, service_name):
        runner.run_remote(target_root, command)

    return {
        "role": "scout",
        "service": service_name,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "dry_run": dry_run,
    }


def deploy_companion(site_config, artifact_run, dry_run=False):
    """Sync the repo, prepare storage, and start the containerized companion stack."""
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    companion = role_config(site_config, "companion")
    workspace_dir = companion["workspace_dir"]
    target_root = companion["ssh"]
    storage = companion.get("storage", {})
    service_name = "auto-scout-companion-runtime.service"

    runner.run_remote(target_root, "mkdir -p '{}'".format(workspace_dir))
    for path in storage.values():
        runner.run_remote(target_root, "sudo mkdir -p '{}'".format(path))
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    for command in _service_install_commands(workspace_dir, service_name):
        runner.run_remote(target_root, command)

    return {
        "role": "companion",
        "service": service_name,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "dry_run": dry_run,
    }

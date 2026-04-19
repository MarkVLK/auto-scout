"""Deployment routines for the clean-slate Scout and companion runtimes."""

import os
import tempfile

from auto_scout.command_runner import CommandRunner
from auto_scout.paths import repo_root
from auto_scout.site_config import companion_storage_root, role_config, role_service_identity


SYNC_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "artifacts/runs",
]


def _render_scout_service(role_settings):
    workspace_dir = role_settings["workspace_dir"]
    service_user, service_group = role_service_identity(role_settings)
    config_path = "{}/config/scout_config.yaml".format(workspace_dir)
    site_path = "{}/config/site.yaml".format(workspace_dir)
    ros_master_uri = role_settings.get("ros", {}).get("master_uri", "http://localhost:11311")

    return """[Unit]
Description=Auto-Scout scout runtime
After=network.target
Wants=network.target

[Service]
Type=simple
User={service_user}
Group={service_group}
WorkingDirectory={workspace_dir}
Environment=AUTO_SCOUT_WORKSPACE={workspace_dir}
Environment=AUTO_SCOUT_CONFIG={config_path}
Environment=AUTO_SCOUT_SITE_CONFIG={site_path}
Environment=ROS_MASTER_URI={ros_master_uri}
Environment=ROS_HOSTNAME=localhost
ExecStart=/bin/bash -lc '{workspace_dir}/scripts/start_scout_runtime.sh'
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
""".format(
        service_user=service_user,
        service_group=service_group,
        workspace_dir=workspace_dir,
        config_path=config_path,
        site_path=site_path,
        ros_master_uri=ros_master_uri,
    )


def _render_companion_service(role_settings):
    workspace_dir = role_settings["workspace_dir"]
    service_user, service_group = role_service_identity(role_settings)
    storage_root = companion_storage_root(role_settings)

    return """[Unit]
Description=Auto-Scout companion runtime
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User={service_user}
Group={service_group}
WorkingDirectory={workspace_dir}
Environment=AUTO_SCOUT_WORKSPACE={workspace_dir}
Environment=AUTO_SCOUT_STORAGE_ROOT={storage_root}
Environment=AUTO_SCOUT_CONFIG={workspace_dir}/config/scout_config.yaml
Environment=AUTO_SCOUT_SITE_CONFIG={workspace_dir}/config/site.yaml
ExecStart=/bin/bash -lc '{workspace_dir}/scripts/start_companion_stack.sh up'
ExecStop=/bin/bash -lc '{workspace_dir}/scripts/start_companion_stack.sh down'
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
""".format(
        service_user=service_user,
        service_group=service_group,
        workspace_dir=workspace_dir,
        storage_root=storage_root,
    )


def _copy_service_to_remote(runner, ssh_config, service_name, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        local_path = handle.name

    remote_temp = "/tmp/{}".format(service_name)
    try:
        runner.copy_to_remote(ssh_config, local_path, remote_temp)
    finally:
        os.unlink(local_path)
    return remote_temp


def _install_service_commands(service_name, remote_temp_path):
    return [
        "sudo install -m 0644 '{}' '/etc/systemd/system/{}'".format(remote_temp_path, service_name),
        "rm -f '{}'".format(remote_temp_path),
        "sudo systemctl daemon-reload",
        "sudo systemctl enable {}".format(service_name),
        "sudo systemctl restart {}".format(service_name),
    ]


def _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group):
    runner.run_remote(target_root, "sudo mkdir -p '{}'".format(workspace_dir))
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))


def deploy_scout(site_config, artifact_run, dry_run=False):
    """Sync the repo and install the Scout runtime service."""
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    scout = role_config(site_config, "scout")
    workspace_dir = scout["workspace_dir"]
    service_name = "auto-scout-scout-runtime.service"
    target_root = scout["ssh"]
    service_user, service_group = role_service_identity(scout)

    _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group)
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))

    remote_temp = _copy_service_to_remote(runner, target_root, service_name, _render_scout_service(scout))
    for command in _install_service_commands(service_name, remote_temp):
        runner.run_remote(target_root, command)

    return {
        "role": "scout",
        "service": service_name,
        "service_group": service_group,
        "service_user": service_user,
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
    service_user, service_group = role_service_identity(companion)

    _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group)
    for path in storage.values():
        runner.run_remote(target_root, "sudo mkdir -p '{}'".format(path))
        runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, path))
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))

    remote_temp = _copy_service_to_remote(
        runner,
        target_root,
        service_name,
        _render_companion_service(companion),
    )
    for command in _install_service_commands(service_name, remote_temp):
        runner.run_remote(target_root, command)

    return {
        "role": "companion",
        "service": service_name,
        "service_group": service_group,
        "service_user": service_user,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "storage_root": companion_storage_root(companion),
        "dry_run": dry_run,
    }

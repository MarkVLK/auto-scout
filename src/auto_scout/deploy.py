"""Deployment routines for the clean-slate Scout and companion runtimes."""

import os
import tempfile

from auto_scout.command_runner import CommandRunner
from auto_scout.paths import repo_root
from auto_scout.site_config import companion_storage_root
from auto_scout.site_config import normalize_drive_model
from auto_scout.site_config import remote_site_config_path
from auto_scout.site_config import role_config
from auto_scout.site_config import role_motion_setting
from auto_scout.site_config import role_service_identity
from auto_scout.yaml_loader import dump_yaml


SYNC_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "artifacts/runs",
]


def _require_configured_setting(setting_name, value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("{} must be set before deploy.".format(setting_name))
    if ".invalid" in value:
        raise ValueError("{} is still using the generated placeholder '{}'.".format(setting_name, value))
    return value


def _render_scout_service(role_settings):
    workspace_dir = role_settings["workspace_dir"]
    service_user, service_group = role_service_identity(role_settings)
    config_path = "{}/config/scout_config.yaml".format(workspace_dir)
    site_path = remote_site_config_path(workspace_dir)
    ros_settings = role_settings.get("ros", {})
    ros_master_uri = _require_configured_setting("scout.ros.master_uri", ros_settings.get("master_uri"))
    advertise_host = _require_configured_setting("scout.ros.advertise_host", ros_settings.get("advertise_host"))

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
Environment=ROS_HOSTNAME={advertise_host}
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
        advertise_host=advertise_host,
    )


def _render_companion_service(role_settings, scout_role_settings):
    workspace_dir = role_settings["workspace_dir"]
    service_user, service_group = role_service_identity(role_settings)
    storage_root = companion_storage_root(role_settings)
    ros_settings = role_settings.get("ros", {})
    ros_master_uri = _require_configured_setting("companion.ros.master_uri", ros_settings.get("master_uri"))
    advertise_host = _require_configured_setting("companion.ros.advertise_host", ros_settings.get("advertise_host"))
    drive_model = normalize_drive_model(role_motion_setting(scout_role_settings, "drive_model"))

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
Environment=AUTO_SCOUT_SITE_CONFIG={site_path}
Environment=AUTO_SCOUT_ROS_MASTER_URI={ros_master_uri}
Environment=AUTO_SCOUT_ROS_HOSTNAME={advertise_host}
Environment=AUTO_SCOUT_ODOM_MODEL_TYPE={drive_model}
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
        site_path=remote_site_config_path(workspace_dir),
        ros_master_uri=ros_master_uri,
        advertise_host=advertise_host,
        drive_model=drive_model,
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


def _copy_site_inventory_to_remote(runner, ssh_config, workspace_dir, site_config):
    remote_path = remote_site_config_path(workspace_dir)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(dump_yaml(site_config))
        local_path = handle.name

    try:
        runner.copy_to_remote(ssh_config, local_path, remote_path)
    finally:
        os.unlink(local_path)
    return remote_path


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
    service_text = _render_scout_service(scout)

    _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group)
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))
    _copy_site_inventory_to_remote(runner, target_root, workspace_dir, site_config)

    remote_temp = _copy_service_to_remote(runner, target_root, service_name, service_text)
    for command in _install_service_commands(service_name, remote_temp):
        runner.run_remote(target_root, command)

    return {
        "role": "scout",
        "service": service_name,
        "service_group": service_group,
        "service_user": service_user,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "remote_site_path": remote_site_config_path(workspace_dir),
        "dry_run": dry_run,
    }


def deploy_companion(site_config, artifact_run, dry_run=False):
    """Sync the repo, prepare storage, and start the containerized companion stack."""
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    scout = role_config(site_config, "scout")
    companion = role_config(site_config, "companion")
    workspace_dir = companion["workspace_dir"]
    target_root = companion["ssh"]
    storage = companion.get("storage", {})
    service_name = "auto-scout-companion-runtime.service"
    service_user, service_group = role_service_identity(companion)
    service_text = _render_companion_service(companion, scout)

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
    _copy_site_inventory_to_remote(runner, target_root, workspace_dir, site_config)

    remote_temp = _copy_service_to_remote(
        runner,
        target_root,
        service_name,
        service_text,
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
        "remote_site_path": remote_site_config_path(workspace_dir),
        "dry_run": dry_run,
    }

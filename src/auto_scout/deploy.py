"""Deployment routines for the clean-slate Scout and companion runtimes."""

from copy import deepcopy
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

ROS_LOG_MAX_AGE_DAYS = 7
ROS_LOG_MAX_BYTES = 100 * 1024 * 1024
SCOUT_ROS_LOG_DIR = "/userdata/auto-scout/ros-logs"
ROS_LOG_CLEANUP_SERVICE = "auto-scout-ros-log-cleanup.service"
ROS_LOG_CLEANUP_TIMER = "auto-scout-ros-log-cleanup.timer"


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
Environment=ROS_LOG_DIR={ros_log_dir}
Environment=ROS_OS_OVERRIDE=debian:stretch
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
        ros_log_dir=SCOUT_ROS_LOG_DIR,
    )


def _render_companion_service(role_settings, scout_role_settings):
    workspace_dir = role_settings["workspace_dir"]
    service_user, service_group = role_service_identity(role_settings)
    storage_root = companion_storage_root(role_settings)
    ros_settings = role_settings.get("ros", {})
    ros_master_uri = _require_configured_setting("companion.ros.master_uri", ros_settings.get("master_uri"))
    advertise_host = _require_configured_setting("companion.ros.advertise_host", ros_settings.get("advertise_host"))
    drive_model = normalize_drive_model(role_motion_setting(scout_role_settings, "drive_model"))
    ros_log_dir = "{}/ros-logs".format(storage_root)

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
Environment=AUTO_SCOUT_ROS_LOG_DIR={ros_log_dir}
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
        ros_log_dir=ros_log_dir,
    )


def _render_ros_log_cleanup_service(workspace_dir, service_user, service_group, ros_log_dir, legacy_log_dirs=None):
    log_paths = [ros_log_dir] + list(legacy_log_dirs or [])
    path_args = " ".join("--path {}".format(path) for path in log_paths)
    return """[Unit]
Description=Auto-Scout ROS log cleanup

[Service]
Type=oneshot
Nice=10
CPUSchedulingPolicy=batch
IOSchedulingClass=idle
User={service_user}
Group={service_group}
WorkingDirectory={workspace_dir}
Environment=ROS_LOG_DIR={ros_log_dir}
Environment=AUTO_SCOUT_ROS_LOG_MAX_AGE_DAYS={max_age_days}
Environment=AUTO_SCOUT_ROS_LOG_MAX_BYTES={max_bytes}
ExecStart=/bin/bash -lc '{workspace_dir}/scripts/cleanup_ros_logs.py {path_args} --max-age-days "$AUTO_SCOUT_ROS_LOG_MAX_AGE_DAYS" --max-bytes "$AUTO_SCOUT_ROS_LOG_MAX_BYTES"'
""".format(
        service_user=service_user,
        service_group=service_group,
        workspace_dir=workspace_dir,
        ros_log_dir=ros_log_dir,
        max_age_days=ROS_LOG_MAX_AGE_DAYS,
        max_bytes=ROS_LOG_MAX_BYTES,
        path_args=path_args,
    )


def _render_ros_log_cleanup_timer():
    return """[Unit]
Description=Run Auto-Scout ROS log cleanup

[Timer]
OnBootSec=5min
OnUnitActiveSec=1d
Persistent=true
Unit={service_name}

[Install]
WantedBy=timers.target
""".format(
        service_name=ROS_LOG_CLEANUP_SERVICE,
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


def _site_inventory_for_remote_role(site_config, role):
    payload = deepcopy(site_config)
    if role == "scout":
        companion = payload.get("roles", {}).get("companion", {})
        companion.setdefault("capabilities", {})["notify"] = False
        companion.setdefault("notifications", {})["webhook_url"] = ""
    return payload


def _copy_site_inventory_to_remote(runner, ssh_config, workspace_dir, site_config, role=None):
    remote_path = remote_site_config_path(workspace_dir)
    payload = _site_inventory_for_remote_role(site_config, role)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(dump_yaml(payload))
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


def _install_timer_commands(service_temp_path, timer_temp_path):
    return [
        "sudo install -m 0644 '{}' '/etc/systemd/system/{}'".format(service_temp_path, ROS_LOG_CLEANUP_SERVICE),
        "sudo install -m 0644 '{}' '/etc/systemd/system/{}'".format(timer_temp_path, ROS_LOG_CLEANUP_TIMER),
        "rm -f '{}' '{}'".format(service_temp_path, timer_temp_path),
        "sudo systemctl daemon-reload",
        "sudo systemctl enable --now {}".format(ROS_LOG_CLEANUP_TIMER),
    ]


def _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group):
    runner.run_remote(target_root, "sudo mkdir -p '{}'".format(workspace_dir))
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))


def _prepare_remote_directory(runner, target_root, path, service_user, service_group):
    runner.run_remote(target_root, "sudo mkdir -p '{}'".format(path))
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, path))


def _install_ros_log_cleanup(runner, target_root, workspace_dir, service_user, service_group, ros_log_dir, legacy_log_dirs=None):
    service_text = _render_ros_log_cleanup_service(
        workspace_dir,
        service_user,
        service_group,
        ros_log_dir,
        legacy_log_dirs=legacy_log_dirs,
    )
    timer_text = _render_ros_log_cleanup_timer()
    service_temp = _copy_service_to_remote(runner, target_root, ROS_LOG_CLEANUP_SERVICE, service_text)
    timer_temp = _copy_service_to_remote(runner, target_root, ROS_LOG_CLEANUP_TIMER, timer_text)
    for command in _install_timer_commands(service_temp, timer_temp):
        runner.run_remote(target_root, command)


def deploy_scout(site_config, artifact_run, dry_run=False):
    """Sync the repo and install the Scout runtime service."""
    runner = CommandRunner(artifact_run=artifact_run, dry_run=dry_run)
    scout = role_config(site_config, "scout")
    workspace_dir = scout["workspace_dir"]
    service_name = "auto-scout-scout-runtime.service"
    target_root = scout["ssh"]
    service_user, service_group = role_service_identity(scout)
    service_text = _render_scout_service(scout)
    ros_log_dir = SCOUT_ROS_LOG_DIR

    _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group)
    _prepare_remote_directory(runner, target_root, ros_log_dir, service_user, service_group)
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))
    _copy_site_inventory_to_remote(runner, target_root, workspace_dir, site_config, role="scout")

    remote_temp = _copy_service_to_remote(runner, target_root, service_name, service_text)
    for command in _install_service_commands(service_name, remote_temp):
        runner.run_remote(target_root, command)
    _install_ros_log_cleanup(
        runner,
        target_root,
        workspace_dir,
        service_user,
        service_group,
        ros_log_dir,
        legacy_log_dirs=["/home/{}/.ros/log".format(service_user)],
    )

    return {
        "role": "scout",
        "service": service_name,
        "service_group": service_group,
        "service_user": service_user,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "ros_log_dir": ros_log_dir,
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
    ros_log_dir = "{}/ros-logs".format(companion_storage_root(companion))

    _prepare_remote_workspace(runner, target_root, workspace_dir, service_user, service_group)
    for path in storage.values():
        _prepare_remote_directory(runner, target_root, path, service_user, service_group)
    _prepare_remote_directory(runner, target_root, ros_log_dir, service_user, service_group)
    runner.rsync_to_remote(
        target_root,
        "{}/".format(repo_root()),
        workspace_dir,
        excludes=SYNC_EXCLUDES,
    )
    runner.run_remote(target_root, "sudo chown -R '{}:{}' '{}'".format(service_user, service_group, workspace_dir))
    _copy_site_inventory_to_remote(runner, target_root, workspace_dir, site_config, role="companion")

    remote_temp = _copy_service_to_remote(
        runner,
        target_root,
        service_name,
        service_text,
    )
    for command in _install_service_commands(service_name, remote_temp):
        runner.run_remote(target_root, command)
    _install_ros_log_cleanup(
        runner,
        target_root,
        workspace_dir,
        service_user,
        service_group,
        ros_log_dir,
        legacy_log_dirs=["/home/{}/.ros/log".format(service_user)],
    )

    return {
        "role": "companion",
        "service": service_name,
        "service_group": service_group,
        "service_user": service_user,
        "workspace_dir": workspace_dir,
        "host": target_root["host"],
        "storage_root": companion_storage_root(companion),
        "ros_log_dir": ros_log_dir,
        "remote_site_path": remote_site_config_path(workspace_dir),
        "dry_run": dry_run,
    }

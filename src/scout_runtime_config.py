#!/usr/bin/env python
"""Python-2-safe configuration helpers for Scout-launched runtime nodes."""

from __future__ import print_function

import getpass
import os
import sys


DEFAULT_SCOUT_SSH_USER = "linaro"
DEFAULT_SCOUT_SSH_HOST = "scout-host-or-ip.invalid"
DEFAULT_SCOUT_WORKSPACE = "/userdata/catkin_ws/src/auto-scout"
DEFAULT_CAMERA_DEVICE = "/dev/video0"
DEFAULT_LIDAR_DEVICE = "/dev/ttyS4"
DEFAULT_SCOUT_DRIVE_MODEL = "diff"
DEFAULT_SSH_AUTH_MODE = "agent"

SCOUT_TOPIC_FALLBACKS = {
    "lidar_scan": "lidar_scan",
    "camera_compressed": "camera_compressed",
    "vendor_camera_jpg": "vendor_camera_jpg",
    "scout_tof": "scout_tof",
    "tof_range": "tof_range",
    "scout_imu": "scout_imu",
    "imu_data": "imu_data",
    "vendor_dog_detection": "external_dog_detection",
    "odom": "odom",
    "vendor_cmd_vel": "vendor_cmd_vel",
    "planner_cmd_vel": "planner_cmd_vel",
    "autonomy_cmd_vel": "autonomy_cmd_vel",
    "safety_state": "safety_state",
    "battery_status": "battery_status",
    "battery_guard_state": "battery_guard_state",
    "battery_guard_control": "battery_guard_control",
    "vendor_dock_status": "vendor_dock_status",
    "runtime_request": "runtime_request",
}

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DEFAULT_SITE_CONFIG = os.path.join(REPO_ROOT, "config", "site.yaml")
DEFAULT_SITE_LOCAL_CONFIG = os.path.join(REPO_ROOT, "config", "site_local.yaml")
DEFAULT_SCOUT_CONFIG = os.path.join(REPO_ROOT, "config", "scout_config.yaml")


def current_username():
    """Return the current OS username or a conservative fallback."""
    return os.environ.get("USER") or getpass.getuser() or "linaro"


def _tool_path():
    return os.path.join(REPO_ROOT, "tools")


def _load_yaml(path):
    try:
        import yaml

        handle = open(path, "r")
        try:
            return yaml.safe_load(handle) or {}
        finally:
            handle.close()
    except ImportError:
        tools_dir = _tool_path()
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from yaml_fallback import YAMLFallback

        handle = open(path, "r")
        try:
            return YAMLFallback.safe_load(handle) or {}
        finally:
            handle.close()


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _default_ssh_auth(mode=DEFAULT_SSH_AUTH_MODE, key_path=""):
    return {
        "mode": str(mode or DEFAULT_SSH_AUTH_MODE).strip().lower(),
        "key_path": str(key_path or ""),
    }


def candidate_config_paths(explicit_path=None):
    """Return config candidates in most-specific to least-specific order."""
    home_dir = os.path.expanduser("~")
    candidates = [
        explicit_path,
        os.environ.get("AUTO_SCOUT_CONFIG"),
        DEFAULT_SCOUT_CONFIG,
        os.path.join(home_dir, "auto-scout", "config", "scout_config.yaml"),
        os.path.join(home_dir, "catkin_ws", "src", "auto-scout", "config", "scout_config.yaml"),
        os.path.join(DEFAULT_SCOUT_WORKSPACE, "config", "scout_config.yaml"),
        "/opt/auto-scout/config/scout_config.yaml",
    ]

    result = []
    seen = set()
    for path in candidates:
        if not path:
            continue
        normalized = os.path.abspath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def candidate_site_paths(explicit_path=None):
    """Return site inventory candidates in merge order."""
    explicit = explicit_path or os.environ.get("AUTO_SCOUT_SITE_CONFIG")
    if explicit:
        return [os.path.abspath(explicit)]

    home_dir = os.path.expanduser("~")
    candidates = [
        DEFAULT_SITE_CONFIG,
        DEFAULT_SITE_LOCAL_CONFIG,
        os.path.join(home_dir, "auto-scout", "config", "site.yaml"),
        os.path.join(home_dir, "auto-scout", "config", "site_local.yaml"),
        os.path.join(home_dir, "catkin_ws", "src", "auto-scout", "config", "site.yaml"),
        os.path.join(home_dir, "catkin_ws", "src", "auto-scout", "config", "site_local.yaml"),
        os.path.join(DEFAULT_SCOUT_WORKSPACE, "config", "site.yaml"),
        os.path.join(DEFAULT_SCOUT_WORKSPACE, "config", "site_local.yaml"),
        "/opt/auto-scout/config/site.yaml",
        "/opt/auto-scout/config/site_local.yaml",
    ]

    result = []
    seen = set()
    for path in candidates:
        if not path:
            continue
        normalized = os.path.abspath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def load_scout_config(explicit_path=None):
    """Load the first readable Scout runtime config and return ``(config, path)``."""
    for path in candidate_config_paths(explicit_path):
        if not os.path.isfile(path):
            continue
        return _load_yaml(path), path
    return {}, None


def default_site_config():
    """Return the Scout defaults needed by source-only runtime nodes."""
    scout_user = DEFAULT_SCOUT_SSH_USER
    return {
        "project": {
            "name": "auto-scout",
            "artifact_root": "artifacts/runs",
        },
        "roles": {
            "scout": {
                "hostname": "moorebot-scout",
                "workspace_dir": DEFAULT_SCOUT_WORKSPACE,
                "ssh": {
                    "host": DEFAULT_SCOUT_SSH_HOST,
                    "user": scout_user,
                    "port": 22,
                    "auth": _default_ssh_auth(),
                },
                "service_user": scout_user,
                "service_group": scout_user,
                "ros": {
                    "distro": "melodic",
                    "master_uri": "http://{}:11311".format(DEFAULT_SCOUT_SSH_HOST),
                    "advertise_host": DEFAULT_SCOUT_SSH_HOST,
                },
                "devices": {
                    "camera": DEFAULT_CAMERA_DEVICE,
                    "lidar": DEFAULT_LIDAR_DEVICE,
                },
                "topics": {
                    "camera_compressed": "/camera/image_raw/compressed",
                    "vendor_camera_jpg": "/CoreNode/jpg",
                    "lidar_scan": "/scan",
                    "odom": "/MotorNode/baselink_odom_relative",
                    "vendor_cmd_vel": "/cmd_vel_force",
                    "planner_cmd_vel": "/scout/cmd_vel_planner",
                    "autonomy_cmd_vel": "/scout/cmd_vel_companion",
                    "safety_state": "/scout/safety_state",
                    "battery_status": "/SensorNode/simple_battery_status",
                    "battery_guard_state": "/scout/battery_guard_state",
                    "battery_guard_control": "/scout/battery_guard_control",
                    "vendor_dock_status": "/CoreNode/going_home_status",
                    "runtime_request": "/scout/runtime/request",
                    "scout_tof": "/SensorNode/tof",
                    "tof_range": "/scout/tof",
                    "scout_imu": "/SensorNode/imu",
                    "imu_data": "/scout/imu/data",
                    "vendor_dog_detection": "/scout/dog_detection_external",
                },
                "motion": {
                    "forward_axis": "y",
                    "drive_model": DEFAULT_SCOUT_DRIVE_MODEL,
                },
                "adapters": {
                    "motion": "rollereye_or_vendor_bridge",
                    "camera": "vendor_jpg_bridge",
                    "lidar": "ld19_serial",
                    "dock": "vendor_dock",
                    "dog_detection": "external_event",
                },
                "capabilities": {
                    "camera": True,
                    "scan": True,
                    "tof": True,
                    "imu": True,
                    "pose": True,
                    "motion": True,
                    "dock": False,
                    "notify": False,
                    "vendor_bridge": True,
                },
                "storage": {
                    "media_cache_dir": "/var/tmp/auto-scout/scout_media_cache",
                    "map_cache_dir": "/var/tmp/auto-scout/scout_map_cache",
                },
            }
        },
    }


def load_site_config(path=None):
    """Load the site inventory with Scout defaults applied."""
    config = default_site_config()
    for candidate in candidate_site_paths(path):
        if not os.path.isfile(candidate):
            continue
        loaded = _load_yaml(candidate)
        if isinstance(loaded, dict):
            _deep_merge(config, loaded)
    return config, path or os.environ.get("AUTO_SCOUT_SITE_CONFIG") or DEFAULT_SITE_LOCAL_CONFIG


def load_site_inventory(explicit_path=None):
    """Return the Scout runtime site inventory."""
    return load_site_config(explicit_path)


def role_config(site_config, role):
    """Return a role config and raise on unknown roles."""
    roles = site_config.get("roles", {})
    if role not in roles:
        raise KeyError("Unknown role '{}'".format(role))
    return roles[role]


def role_topic(role_settings, name, default=None):
    return role_settings.get("topics", {}).get(name, default)


def role_device(role_settings, name, default=None):
    return role_settings.get("devices", {}).get(name, default)


def role_motion_setting(role_settings, name, default=None):
    return role_settings.get("motion", {}).get(name, default)


def role_ros_setting(role_settings, name, default=None):
    return role_settings.get("ros", {}).get(name, default)


def scout_runtime_topic(site_config, project_config, name, default=None):
    scout = role_config(site_config, "scout")
    if name in scout.get("topics", {}):
        return scout["topics"][name]

    fallback_key = SCOUT_TOPIC_FALLBACKS.get(name, name)
    return project_config.get("topics", {}).get(fallback_key, default)


def scout_runtime_device(site_config, project_config, name, default=None):
    scout = role_config(site_config, "scout")
    if name in scout.get("devices", {}):
        return scout["devices"][name]

    if name == "camera":
        return project_config.get("camera", {}).get("device", default)
    if name == "lidar":
        return project_config.get("lidar", {}).get("port", default)
    return default

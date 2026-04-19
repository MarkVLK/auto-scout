"""Inventory loading and persistence for Scout and companion hosts."""

from copy import deepcopy
import getpass
import os

from auto_scout.paths import DEFAULT_SITE_CONFIG
from auto_scout.yaml_loader import load_yaml, write_yaml


DEFAULT_SCOUT_SSH_USER = "linaro"
DEFAULT_SCOUT_SSH_HOST = "moorebot-scout.local"
DEFAULT_COMPANION_SSH_HOST = "auto-scout-pi5.local"
DEFAULT_COMPANION_STORAGE_ROOT = "/srv/auto-scout"

SCOUT_TOPIC_FALLBACKS = {
    "lidar_scan": "lidar_scan",
    "camera_compressed": "camera_compressed",
    "vendor_dog_detection": "external_dog_detection",
    "odom": "odom",
    "vendor_cmd_vel": "vendor_cmd_vel",
    "autonomy_cmd_vel": "autonomy_cmd_vel",
}


def current_username():
    """Return the current OS username or a conservative fallback."""
    return os.environ.get("USER") or getpass.getuser() or "ubuntu"


def scout_workspace_for_user(user):
    """Return the default Scout workspace for the given user."""
    return "/userdata/catkin_ws/src/auto-scout"


def companion_workspace_for_user(user):
    """Return the default companion workspace for the given user."""
    return "/home/{}/auto-scout".format(user)


def scout_cache_paths():
    """Return generic Scout cache locations that do not assume a username."""
    return {
        "media_cache_dir": "/var/tmp/auto-scout/scout_media_cache",
        "map_cache_dir": "/var/tmp/auto-scout/scout_map_cache",
    }


def companion_storage_paths(root):
    """Return maps/media/events directories under a single storage root."""
    normalized_root = str(root).rstrip("/") or DEFAULT_COMPANION_STORAGE_ROOT
    return {
        "maps_dir": "{}/maps".format(normalized_root),
        "media_dir": "{}/media".format(normalized_root),
        "events_dir": "{}/events".format(normalized_root),
    }


def companion_storage_root(role_settings):
    """Return the common storage root for the companion role."""
    storage = role_settings.get("storage", {})
    maps_dir = storage.get("maps_dir")
    media_dir = storage.get("media_dir")
    events_dir = storage.get("events_dir")
    paths = [path for path in [maps_dir, media_dir, events_dir] if path]
    if not paths:
        return DEFAULT_COMPANION_STORAGE_ROOT

    parents = {os.path.dirname(path.rstrip("/")) for path in paths}
    if len(parents) == 1:
        return parents.pop()

    common_root = os.path.commonpath(paths)
    if common_root == "/":
        return DEFAULT_COMPANION_STORAGE_ROOT
    return common_root.rstrip("/")


def default_site_config():
    """Build a site inventory with environment-aware defaults."""
    companion_user = current_username()
    scout_user = DEFAULT_SCOUT_SSH_USER

    return {
        "project": {
            "name": "auto-scout",
            "artifact_root": "artifacts/runs",
        },
        "roles": {
            "scout": {
                "hostname": "moorebot-scout",
                "workspace_dir": scout_workspace_for_user(scout_user),
                "ssh": {
                    "host": DEFAULT_SCOUT_SSH_HOST,
                    "user": scout_user,
                    "port": 22,
                },
                "service_user": scout_user,
                "service_group": scout_user,
                "ros": {
                    "distro": "melodic",
                    "master_uri": "http://{}:11311".format(DEFAULT_SCOUT_SSH_HOST),
                    "advertise_host": DEFAULT_SCOUT_SSH_HOST,
                },
                "devices": {
                    "camera": "/dev/video0",
                    "lidar": "/dev/ttyS4",
                },
                "topics": {
                    "camera_compressed": "/camera/image_raw/compressed",
                    "lidar_scan": "/scan",
                    "odom": "/MotorNode/baselink_odom_relative",
                    "vendor_cmd_vel": "/cmd_vel_force",
                    "autonomy_cmd_vel": "/scout/cmd_vel_companion",
                    "vendor_dog_detection": "/scout/dog_detection_external",
                },
                "motion": {
                    "forward_axis": "y",
                },
                "adapters": {
                    "motion": "rollereye_or_vendor_bridge",
                    "camera": "opencv_device",
                    "lidar": "ld19_serial",
                    "dock": "vendor_dock",
                    "dog_detection": "external_event",
                },
                "capabilities": {
                    "camera": True,
                    "scan": True,
                    "pose": True,
                    "motion": True,
                    "dock": False,
                    "notify": False,
                    "vendor_bridge": True,
                },
                "storage": scout_cache_paths(),
            },
            "companion": {
                "hostname": "pi5-companion",
                "workspace_dir": companion_workspace_for_user(companion_user),
                "ssh": {
                    "host": DEFAULT_COMPANION_SSH_HOST,
                    "user": companion_user,
                    "port": 22,
                },
                "service_user": companion_user,
                "service_group": companion_user,
                "host_os": {
                    "name": "ubuntu",
                    "version": "24.04",
                    "arch": "arm64",
                },
                "ros": {
                    "containerized": True,
                    "distro": "melodic",
                    "container_name": "auto-scout-melodic",
                    "compose_file": "container/docker-compose.yml",
                    "master_uri": "http://{}:11311".format(DEFAULT_SCOUT_SSH_HOST),
                    "advertise_host": DEFAULT_COMPANION_SSH_HOST,
                },
                "capabilities": {
                    "camera": False,
                    "scan": True,
                    "pose": False,
                    "dock": False,
                    "notify": False,
                },
                "storage": companion_storage_paths(DEFAULT_COMPANION_STORAGE_ROOT),
                "notifications": {
                    "webhook_url": "",
                },
            },
        },
    }


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_site_config(path=None):
    """Load the site inventory with defaults applied."""
    site_path = path or os.environ.get("AUTO_SCOUT_SITE_CONFIG") or str(DEFAULT_SITE_CONFIG)
    config = default_site_config()

    if os.path.isfile(site_path):
        loaded = load_yaml(site_path)
        if isinstance(loaded, dict):
            _deep_merge(config, loaded)

    return config, site_path


def write_site_config(site_config, path=None):
    """Persist the site inventory to disk."""
    site_path = path or os.environ.get("AUTO_SCOUT_SITE_CONFIG") or str(DEFAULT_SITE_CONFIG)
    return write_yaml(site_path, site_config)


def role_config(site_config, role):
    """Return a role config and raise on unknown roles."""
    try:
        return site_config["roles"][role]
    except KeyError as exc:
        raise KeyError("Unknown role '{}'".format(role)) from exc


def role_topic(role_settings, name, default=None):
    """Return a role topic setting."""
    return role_settings.get("topics", {}).get(name, default)


def role_device(role_settings, name, default=None):
    """Return a role device setting."""
    return role_settings.get("devices", {}).get(name, default)


def role_motion_setting(role_settings, name, default=None):
    """Return a role motion setting."""
    return role_settings.get("motion", {}).get(name, default)


def role_ros_setting(role_settings, name, default=None):
    """Return a role ROS setting."""
    return role_settings.get("ros", {}).get(name, default)


def scout_runtime_topic(site_config, project_config, name, default=None):
    """Return the canonical Scout runtime topic with legacy fallbacks."""
    scout = role_config(site_config, "scout")
    if name in scout.get("topics", {}):
        return scout["topics"][name]

    fallback_key = SCOUT_TOPIC_FALLBACKS.get(name, name)
    return project_config.get("topics", {}).get(fallback_key, default)


def scout_runtime_device(site_config, project_config, name, default=None):
    """Return the canonical Scout runtime device with legacy fallbacks."""
    scout = role_config(site_config, "scout")
    if name in scout.get("devices", {}):
        return scout["devices"][name]

    if name == "camera":
        return project_config.get("camera", {}).get("device", default)
    if name == "lidar":
        return project_config.get("lidar", {}).get("port", default)
    return default


def scout_motion_axis(site_config, default="y"):
    """Return the configured Scout forward axis."""
    scout = role_config(site_config, "scout")
    return role_motion_setting(scout, "forward_axis", default)


def role_service_identity(role_settings):
    """Return the service user/group for a role."""
    ssh_user = role_settings.get("ssh", {}).get("user", current_username())
    service_user = role_settings.get("service_user") or ssh_user
    service_group = role_settings.get("service_group") or service_user
    return service_user, service_group


def system_capabilities(site_config):
    """Return the union of declared capabilities across both roles."""
    merged = {}
    for role_name in ["scout", "companion"]:
        role = site_config.get("roles", {}).get(role_name, {})
        for name, value in role.get("capabilities", {}).items():
            merged[name] = merged.get(name, False) or bool(value)
    return merged

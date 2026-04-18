"""Inventory loading for Scout and companion hosts."""

from copy import deepcopy
import os

from auto_scout.paths import DEFAULT_SITE_CONFIG
from auto_scout.yaml_loader import load_yaml


DEFAULT_SITE = {
    "project": {
        "name": "auto-scout",
        "artifact_root": "artifacts/runs",
    },
    "roles": {
        "scout": {
            "hostname": "moorebot-scout",
            "workspace_dir": "/home/linaro/catkin_ws/src/auto-scout",
            "ssh": {
                "host": "192.168.1.199",
                "user": "linaro",
                "port": 22,
            },
            "ros": {
                "distro": "melodic",
                "master_uri": "http://localhost:11311",
            },
            "devices": {
                "camera": "/dev/video0",
                "lidar": "/dev/ttyUSB0",
            },
            "topics": {
                "camera_compressed": "/camera/image_raw/compressed",
                "lidar_scan": "/scan",
                "vendor_dog_detection": "/scout/dog_detection_external",
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
                "pose": False,
                "dock": False,
                "notify": False,
                "vendor_bridge": True,
            },
            "storage": {
                "media_cache_dir": "/home/linaro/scout_media_cache",
                "map_cache_dir": "/home/linaro/scout_map_cache",
            },
        },
        "companion": {
            "hostname": "pi5-companion",
            "workspace_dir": "/opt/auto-scout",
            "ssh": {
                "host": "auto-scout-pi5.local",
                "user": "ubuntu",
                "port": 22,
            },
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
            },
            "capabilities": {
                "camera": False,
                "scan": True,
                "pose": False,
                "dock": False,
                "notify": False,
            },
            "storage": {
                "maps_dir": "/srv/auto-scout/maps",
                "media_dir": "/srv/auto-scout/media",
                "events_dir": "/srv/auto-scout/events",
            },
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
    config = deepcopy(DEFAULT_SITE)

    if os.path.isfile(site_path):
        loaded = load_yaml(site_path)
        if isinstance(loaded, dict):
            _deep_merge(config, loaded)

    return config, site_path


def role_config(site_config, role):
    """Return a role config and raise on unknown roles."""
    try:
        return site_config["roles"][role]
    except KeyError as exc:
        raise KeyError("Unknown role '{}'".format(role)) from exc


def system_capabilities(site_config):
    """Return the union of declared capabilities across both roles."""
    merged = {}
    for role_name in ["scout", "companion"]:
        role = site_config.get("roles", {}).get(role_name, {})
        for name, value in role.get("capabilities", {}).items():
            merged[name] = merged.get(name, False) or bool(value)
    return merged

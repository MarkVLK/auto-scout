#!/usr/bin/env python
"""Python-2-safe helpers for companion ROS runtime scripts."""

from __future__ import print_function

from datetime import datetime
import os

from scout_runtime_config import REPO_ROOT
from scout_runtime_config import _load_yaml
from scout_runtime_config import load_site_config
from scout_runtime_config import role_config
from scout_runtime_config import scout_runtime_topic


DEFAULT_MISSION_DIR = os.path.join(REPO_ROOT, "config", "missions")


def utc_timestamp():
    """Return an ISO-8601 UTC timestamp."""
    return datetime.utcnow().isoformat() + "Z"


def ensure_directory(path):
    """Create a directory when it does not already exist."""
    if not os.path.isdir(path):
        os.makedirs(path)


def mission_path(name_or_path):
    """Resolve a mission name or explicit path to a YAML file."""
    if os.path.isfile(name_or_path):
        return os.path.abspath(name_or_path)

    candidate = os.path.join(DEFAULT_MISSION_DIR, "{}.yaml".format(name_or_path))
    if os.path.isfile(candidate):
        return candidate

    raise IOError("Mission config not found: {}".format(name_or_path))


def load_mission_config(name_or_path):
    """Load a mission config using the Scout runtime YAML helpers."""
    path = mission_path(name_or_path)
    config = _load_yaml(path)
    if not isinstance(config, dict):
        raise ValueError("Mission config must be a mapping: {}".format(path))
    return config, path


def system_capabilities(site_config):
    """Return the union of declared capabilities across both roles."""
    merged = {}
    for role_name in ["scout", "companion"]:
        role_settings = site_config.get("roles", {}).get(role_name, {})
        for name, value in role_settings.get("capabilities", {}).items():
            merged[name] = merged.get(name, False) or bool(value)
    return merged

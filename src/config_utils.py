#!/usr/bin/env python3
"""Helpers for locating and loading reset-era configuration files."""

import os
from pathlib import Path

from auto_scout.paths import DEFAULT_SCOUT_CONFIG
from auto_scout.site_config import load_site_config
from auto_scout.yaml_loader import load_yaml


def candidate_config_paths(explicit_path=None):
    """Return config candidates in most-specific to least-specific order."""
    home_dir = str(Path.home())
    candidates = [
        explicit_path,
        os.environ.get("AUTO_SCOUT_CONFIG"),
        str(DEFAULT_SCOUT_CONFIG),
        os.path.join(home_dir, "auto-scout", "config", "scout_config.yaml"),
        os.path.join(home_dir, "catkin_ws", "src", "auto-scout", "config", "scout_config.yaml"),
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


def load_scout_config(explicit_path=None):
    """Load the first readable Scout runtime config and return (config, path)."""
    for path in candidate_config_paths(explicit_path):
        if not os.path.isfile(path):
            continue
        return load_yaml(path), path
    return {}, None


def load_site_inventory(explicit_path=None):
    """Return the reset-era site inventory."""
    return load_site_config(explicit_path)

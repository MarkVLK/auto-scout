"""Mission configuration helpers."""

import os

from auto_scout.paths import DEFAULT_MISSION_DIR
from auto_scout.yaml_loader import load_yaml


def mission_path(name_or_path):
    """Resolve a mission name or explicit path to a YAML file."""
    if os.path.isfile(name_or_path):
        return name_or_path

    candidate = os.path.join(str(DEFAULT_MISSION_DIR), "{}.yaml".format(name_or_path))
    if os.path.isfile(candidate):
        return candidate

    raise FileNotFoundError(name_or_path)


def load_mission_config(name_or_path):
    """Load a mission definition."""
    path = mission_path(name_or_path)
    config = load_yaml(path)
    if not isinstance(config, dict):
        raise ValueError("Mission config must be a mapping: {}".format(path))
    return config, path

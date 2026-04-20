"""Common path helpers for the clean-slate runtime."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SITE_CONFIG = REPO_ROOT / "config" / "site.yaml"
DEFAULT_SITE_LOCAL_CONFIG = REPO_ROOT / "config" / "site_local.yaml"
DEFAULT_SCOUT_CONFIG = REPO_ROOT / "config" / "scout_config.yaml"
DEFAULT_MISSION_DIR = REPO_ROOT / "config" / "missions"
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "runs"


def repo_root():
    """Return the repository root."""
    return REPO_ROOT

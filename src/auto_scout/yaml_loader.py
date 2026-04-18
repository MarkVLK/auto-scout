"""YAML loading helpers with a repo-local fallback parser."""

from pathlib import Path
import sys

from auto_scout.paths import repo_root


def load_yaml(path):
    """Load YAML from path, preferring PyYAML and falling back to the repo parser."""
    yaml_path = Path(path)
    if not yaml_path.is_file():
        raise FileNotFoundError(str(yaml_path))

    try:
        import yaml

        with yaml_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except ImportError:
        tools_dir = repo_root() / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from yaml_fallback import YAMLFallback

        with yaml_path.open("r", encoding="utf-8") as handle:
            return YAMLFallback.safe_load(handle) or {}

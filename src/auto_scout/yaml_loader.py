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


def _dump_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"{}"'.format(escaped)


def _dump_yaml_fallback(value, indent=0):
    prefix = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append("{}{}:".format(prefix, key))
                lines.append(_dump_yaml_fallback(item, indent + 2))
            else:
                lines.append("{}{}: {}".format(prefix, key, _dump_scalar(item)))
        return "\n".join(lines)

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append("{}-".format(prefix))
                lines.append(_dump_yaml_fallback(item, indent + 2))
            else:
                lines.append("{}- {}".format(prefix, _dump_scalar(item)))
        return "\n".join(lines)

    return "{}{}".format(prefix, _dump_scalar(value))


def dump_yaml(payload):
    """Serialize YAML for repo config files with a simple fallback dumper."""
    try:
        import yaml

        return yaml.safe_dump(payload, sort_keys=False)
    except ImportError:
        return _dump_yaml_fallback(payload) + "\n"


def write_yaml(path, payload):
    """Write YAML to disk, creating parent directories as needed."""
    yaml_path = Path(path)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(dump_yaml(payload), encoding="utf-8")
    return yaml_path

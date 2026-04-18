"""Artifact helpers for validations, deployments, and mission runs."""

from datetime import datetime, timezone
import json
from pathlib import Path

from auto_scout.paths import DEFAULT_ARTIFACT_ROOT


def _slug(value):
    return "".join(char if char.isalnum() or char in ["-", "_"] else "-" for char in value).strip("-")


class ArtifactRun:
    """Capture structured outputs for a single CLI invocation."""

    def __init__(self, name, root=None):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base_root = Path(root) if root else DEFAULT_ARTIFACT_ROOT
        self.path = base_root / "{}-{}".format(timestamp, _slug(name))
        self.path.mkdir(parents=True, exist_ok=True)
        self.log_path = self.path / "run.log"
        self.meta_path = self.path / "meta.json"
        self.write_json(
            "meta.json",
            {
                "name": name,
                "created_at": timestamp,
                "artifact_dir": str(self.path),
            },
        )

    def log(self, message):
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write("{}\n".format(message))

    def write_json(self, relative_path, payload):
        target = self.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def write_text(self, relative_path, content):
        target = self.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            handle.write(content)
        return target

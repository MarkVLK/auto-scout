#!/usr/bin/env python3
"""Unit tests for layered site inventory loading."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.site_config import default_site_config
from auto_scout.site_config import load_site_config
from auto_scout.site_config import write_site_config
from auto_scout.yaml_loader import load_yaml
from auto_scout.yaml_loader import write_yaml


class SiteConfigLoaderTest(unittest.TestCase):
    """Verify tracked-sample plus local-override loading semantics."""

    def test_load_site_config_merges_sample_then_local_and_returns_local_write_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            sample_path = temp_root / "site.yaml"
            local_path = temp_root / "site_local.yaml"

            sample = default_site_config()
            sample["roles"]["scout"]["ssh"]["host"] = "scout.example.test"
            sample["roles"]["companion"]["ssh"]["host"] = "companion.example.test"
            write_yaml(sample_path, sample)
            write_yaml(
                local_path,
                {
                    "roles": {
                        "scout": {
                            "ssh": {"host": "192.0.2.10"},
                            "ros": {"advertise_host": "192.0.2.10"},
                        }
                    }
                },
            )

            with patch("auto_scout.site_config.DEFAULT_SITE_CONFIG", sample_path), patch(
                "auto_scout.site_config.DEFAULT_SITE_LOCAL_CONFIG", local_path
            ):
                site_config, site_path = load_site_config()

        self.assertEqual(site_path, str(local_path))
        self.assertEqual(site_config["roles"]["scout"]["ssh"]["host"], "192.0.2.10")
        self.assertEqual(site_config["roles"]["scout"]["ros"]["advertise_host"], "192.0.2.10")
        self.assertEqual(site_config["roles"]["companion"]["ssh"]["host"], "companion.example.test")

    def test_write_site_config_defaults_to_site_local(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            sample_path = temp_root / "site.yaml"
            local_path = temp_root / "site_local.yaml"
            sample = default_site_config()
            write_yaml(sample_path, sample)

            updated = default_site_config()
            updated["roles"]["companion"]["ssh"]["host"] = "companion.example.test"

            with patch("auto_scout.site_config.DEFAULT_SITE_CONFIG", sample_path), patch(
                "auto_scout.site_config.DEFAULT_SITE_LOCAL_CONFIG", local_path
            ):
                write_site_config(updated)

            written = load_yaml(local_path)
            sample_written = load_yaml(sample_path)

        self.assertEqual(written["roles"]["companion"]["ssh"]["host"], "companion.example.test")
        self.assertTrue(sample_written["roles"]["companion"]["ssh"]["host"].endswith(".invalid"))


if __name__ == "__main__":
    unittest.main()

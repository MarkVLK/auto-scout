#!/usr/bin/env python3
"""Unit tests for remote access helpers."""

import socket
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.command_runner import CommandRunner
from auto_scout.network_validation import validate_host_syntax
from auto_scout.network_validation import validate_site_connectivity
from auto_scout.site_config import default_site_config


class DummyRunner(CommandRunner):
    """Small command runner double for remote validation tests."""

    def __init__(self, ok=True, tty=True):
        super().__init__()
        self._ok = ok
        self._tty = tty
        self.commands = []

    def tty_available(self):
        return self._tty

    def run(self, command, cwd=None, check=True):
        self.commands.append(command if isinstance(command, str) else " ".join(command))

        class Result:
            def __init__(self, ok):
                self.ok = ok
                self.stdout = ""
                self.stderr = "" if ok else "permission denied"

        return Result(self._ok)


class RemoteAccessTest(unittest.TestCase):
    """Verify SSH command construction and connectivity validation."""

    def test_command_runner_builds_agent_key_and_password_ssh_commands(self):
        runner = CommandRunner()
        base = {
            "host": "scout.example.test",
            "user": "linaro",
            "port": 2222,
            "auth": {"mode": "agent", "key_path": ""},
        }

        agent_command = runner.build_ssh_command(base, "true")
        self.assertIn("BatchMode=yes", " ".join(agent_command))
        self.assertNotIn("-i", agent_command)

        key_command = runner.build_ssh_command(
            dict(base, auth={"mode": "key", "key_path": "/tmp/scout-key"}),
            "true",
        )
        self.assertIn("-i", key_command)
        self.assertIn("/tmp/scout-key", key_command)

        password_command = runner.build_ssh_command(
            dict(base, auth={"mode": "password", "key_path": ""}),
            "true",
        )
        rendered = " ".join(password_command)
        self.assertIn("BatchMode=no", rendered)
        self.assertIn("PreferredAuthentications=password,keyboard-interactive", rendered)

    def test_password_auth_requires_tty_before_remote_execution(self):
        runner = DummyRunner(tty=False)
        with self.assertRaises(RuntimeError):
            runner.run_remote(
                {
                    "host": "scout.example.test",
                    "user": "linaro",
                    "port": 22,
                    "auth": {"mode": "password", "key_path": ""},
                },
                "true",
            )

    def test_validate_site_connectivity_reports_invalid_uri_and_missing_key_path(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ssh"]["host"] = "scout.example.test"
        site_config["roles"]["scout"]["ssh"]["auth"]["mode"] = "key"
        site_config["roles"]["scout"]["ssh"]["auth"]["key_path"] = ""
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "scout.example.test"
        site_config["roles"]["scout"]["ros"]["master_uri"] = "not-a-uri"

        payload = validate_site_connectivity(
            site_config,
            ["scout"],
            validate_ssh_auth=False,
            resolver=lambda host: None,
            connector=lambda host, port, timeout: None,
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(any("ssh.auth.key_path" in item for item in payload["errors"]))
        self.assertTrue(any("ros.master_uri" in item for item in payload["errors"]))

    def test_validate_site_connectivity_reports_unreachable_endpoints(self):
        site_config = default_site_config()
        site_config["roles"]["companion"]["ssh"]["host"] = "companion.example.test"
        site_config["roles"]["companion"]["ros"]["advertise_host"] = "companion.example.test"
        site_config["roles"]["companion"]["ros"]["master_uri"] = "http://192.0.2.10:11311"

        def connector(host, port, timeout):
            raise OSError("refused")

        payload = validate_site_connectivity(
            site_config,
            ["companion"],
            validate_ssh_auth=False,
            resolver=lambda host: None,
            connector=connector,
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(any("ssh endpoint" in item for item in payload["errors"]))
        self.assertTrue(any("ros.master_uri endpoint" in item for item in payload["errors"]))

    def test_validate_site_connectivity_reports_unresolved_hostname(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ssh"]["host"] = "missing.example.test"
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "missing.example.test"
        site_config["roles"]["scout"]["ros"]["master_uri"] = "http://missing.example.test:11311"

        def resolver(host):
            raise socket.gaierror("no such host")

        payload = validate_site_connectivity(
            site_config,
            ["scout"],
            validate_ssh_auth=False,
            resolver=resolver,
            connector=lambda host, port, timeout: None,
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(any("did not resolve" in item for item in payload["errors"]))

    def test_validate_site_connectivity_accepts_mdns_hostnames(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["ssh"]["host"] = "moorebot-scout.local"
        site_config["roles"]["scout"]["ros"]["advertise_host"] = "moorebot-scout.local"
        site_config["roles"]["scout"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"
        site_config["roles"]["companion"]["ssh"]["host"] = "auto-scout-pi5.local"
        site_config["roles"]["companion"]["ros"]["advertise_host"] = "auto-scout-pi5.local"
        site_config["roles"]["companion"]["ros"]["master_uri"] = "http://moorebot-scout.local:11311"

        payload = validate_site_connectivity(
            site_config,
            ["scout", "companion"],
            validate_ssh_auth=False,
            resolver=lambda host: None,
            connector=lambda host, port, timeout: None,
        )

        self.assertIsNone(validate_host_syntax("moorebot-scout.local"))
        self.assertIsNone(validate_host_syntax("auto-scout-pi5.local"))
        self.assertTrue(payload["ok"], msg=payload["errors"])


if __name__ == "__main__":
    unittest.main()

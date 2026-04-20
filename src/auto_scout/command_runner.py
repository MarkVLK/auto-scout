"""Helpers for local and remote command execution."""

from dataclasses import dataclass
import shlex
import subprocess
import sys

from auto_scout.site_config import normalize_ssh_auth_mode


DEFAULT_SSH_CONNECT_TIMEOUT = 5


@dataclass
class CommandResult:
    """Normalized command execution result."""

    ok: bool
    command: str
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool = False


class CommandRunner:
    """Run commands locally or over SSH, with dry-run support."""

    def __init__(self, artifact_run=None, dry_run=False):
        self.artifact_run = artifact_run
        self.dry_run = dry_run

    def _record(self, message):
        if self.artifact_run:
            self.artifact_run.log(message)

    def tty_available(self):
        """Return whether this process can safely allow password prompts."""
        return bool(sys.stdin.isatty())

    def run(self, command, cwd=None, check=True):
        command_text = command if isinstance(command, str) else shlex.join(command)
        self._record("$ {}".format(command_text))
        if self.dry_run:
            return CommandResult(True, command_text, 0, "", "", dry_run=True)

        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=isinstance(command, str),
        )
        if completed.stdout:
            self._record(completed.stdout.rstrip())
        if completed.stderr:
            self._record(completed.stderr.rstrip())
        if check and completed.returncode != 0:
            raise RuntimeError(
                "Command failed ({}): {}".format(completed.returncode, command_text)
            )
        return CommandResult(
            ok=completed.returncode == 0,
            command=command_text,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _ssh_auth_settings(self, ssh_config):
        auth = ssh_config.get("auth", {})
        mode = normalize_ssh_auth_mode(auth.get("mode"))
        return {
            "mode": mode,
            "key_path": str(auth.get("key_path") or ""),
        }

    def _ssh_options(self, ssh_config, port_flag, batch_mode=None, connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT):
        auth = self._ssh_auth_settings(ssh_config)
        if batch_mode is None:
            batch_mode = auth["mode"] in ["agent", "key"]

        options = [
            port_flag,
            str(ssh_config.get("port", 22)),
            "-o",
            "ConnectTimeout={}".format(int(connect_timeout)),
            "-o",
            "BatchMode={}".format("yes" if batch_mode else "no"),
        ]

        if auth["mode"] == "password":
            options.extend(
                [
                    "-o",
                    "PreferredAuthentications=password,keyboard-interactive",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )
        elif auth["mode"] == "key" and auth["key_path"]:
            options.extend(["-i", auth["key_path"]])

        return options

    def _require_password_tty(self, ssh_config):
        auth = self._ssh_auth_settings(ssh_config)
        if auth["mode"] == "password" and not self.dry_run and not self.tty_available():
            raise RuntimeError(
                "SSH password authentication requires an interactive terminal. "
                "Rerun interactively or switch the role to SSH agent/key auth."
            )

    def ssh_target(self, ssh_config):
        """Return the user@host target string for SSH operations."""
        return "{}@{}".format(ssh_config["user"], ssh_config["host"])

    def build_ssh_command(
        self,
        ssh_config,
        remote_command,
        batch_mode=None,
        connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    ):
        """Return a full SSH command list."""
        command = ["ssh"]
        command.extend(self._ssh_options(ssh_config, "-p", batch_mode=batch_mode, connect_timeout=connect_timeout))
        command.extend([self.ssh_target(ssh_config), remote_command])
        return command

    def build_scp_command(
        self,
        ssh_config,
        source_path,
        target_path,
        batch_mode=None,
        connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    ):
        """Return a full SCP command list."""
        command = ["scp"]
        command.extend(self._ssh_options(ssh_config, "-P", batch_mode=batch_mode, connect_timeout=connect_timeout))
        command.extend([source_path, "{}:{}".format(self.ssh_target(ssh_config), target_path)])
        return command

    def build_rsync_command(
        self,
        ssh_config,
        source_dir,
        target_dir,
        excludes=None,
        delete=False,
        batch_mode=None,
        connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    ):
        """Return a full rsync command list."""
        transport = ["ssh"]
        transport.extend(self._ssh_options(ssh_config, "-p", batch_mode=batch_mode, connect_timeout=connect_timeout))

        command = ["rsync", "-az", "-e", shlex.join(transport)]
        if delete:
            command.append("--delete")
        for item in excludes or []:
            command.extend(["--exclude", item])
        command.extend([source_dir, "{}:{}".format(self.ssh_target(ssh_config), target_dir)])
        return command

    def run_remote(self, ssh_config, remote_command, check=True, batch_mode=None, connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT):
        self._require_password_tty(ssh_config)
        return self.run(
            self.build_ssh_command(
                ssh_config,
                remote_command,
                batch_mode=batch_mode,
                connect_timeout=connect_timeout,
            ),
            check=check,
        )

    def rsync_to_remote(
        self,
        ssh_config,
        source_dir,
        target_dir,
        excludes=None,
        delete=False,
        batch_mode=None,
        connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    ):
        self._require_password_tty(ssh_config)
        return self.run(
            self.build_rsync_command(
                ssh_config,
                source_dir,
                target_dir,
                excludes=excludes,
                delete=delete,
                batch_mode=batch_mode,
                connect_timeout=connect_timeout,
            )
        )

    def copy_to_remote(
        self,
        ssh_config,
        source_path,
        target_path,
        batch_mode=None,
        connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    ):
        """Copy one local file to a remote path using SCP."""
        self._require_password_tty(ssh_config)
        return self.run(
            self.build_scp_command(
                ssh_config,
                source_path,
                target_path,
                batch_mode=batch_mode,
                connect_timeout=connect_timeout,
            )
        )

"""Helpers for local and remote command execution."""

from dataclasses import dataclass
import shlex
import subprocess


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

    def run_remote(self, ssh_config, remote_command, check=True):
        target = "{}@{}".format(ssh_config["user"], ssh_config["host"])
        port = str(ssh_config.get("port", 22))
        return self.run(
            ["ssh", "-p", port, target, remote_command],
            check=check,
        )

    def rsync_to_remote(self, ssh_config, source_dir, target_dir, excludes=None, delete=False):
        port = str(ssh_config.get("port", 22))
        target = "{}@{}:{}".format(ssh_config["user"], ssh_config["host"], target_dir)
        command = ["rsync", "-az", "-e", "ssh -p {}".format(port)]
        if delete:
            command.append("--delete")
        for item in excludes or []:
            command.extend(["--exclude", item])
        command.extend([source_dir, target])
        return self.run(command)

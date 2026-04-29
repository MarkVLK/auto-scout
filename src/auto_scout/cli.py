"""Headless CLI for the clean-slate Auto-Scout reset."""

import argparse
import json
import os
import subprocess
import sys
import threading
import json as _json
import urllib.request

try:
    import requests
except ImportError:
    requests = None

from auto_scout.artifacts import ArtifactRun
from auto_scout.command_runner import CommandRunner
from auto_scout.deploy import deploy_companion, deploy_scout
from auto_scout.install_config import configure_role, prompts_enabled
from auto_scout.live_probe import apply_probe_suggestions, probe_scout_capabilities
from auto_scout.mission_config import load_mission_config
from auto_scout.mission_runner import run_smoke_loop
from auto_scout.network_validation import role_needs_network_prompt
from auto_scout.network_validation import validate_site_connectivity
from auto_scout.paths import DEFAULT_SCOUT_CONFIG, repo_root
from auto_scout.redaction import redact_sensitive
from auto_scout.site_config import load_site_config, role_config, write_site_config
from auto_scout.notifications import build_test_notification_payload
from auto_scout.notifications import companion_notification_webhook_url
from auto_scout.notifications import DEFAULT_TEST_MESSAGE


def _validator_command(
    role,
    site_path,
    config_path,
    no_live_probe=False,
    observe_motion=None,
    exercise_cmd_vel=False,
    skip_connectivity_check=False,
    quiet=False,
):
    mode = "all" if role == "system" else "runtime"
    command = [
        sys.executable,
        os.path.join(str(repo_root()), "check_scout_compatibility.py"),
        "--mode",
        mode,
        "--role",
        role,
        "--site",
        site_path,
        "--config",
        config_path,
        "--json",
    ]
    if no_live_probe:
        command.append("--no-live-probe")
    if observe_motion is not None:
        command.extend(["--observe-motion", str(observe_motion)])
    if exercise_cmd_vel:
        command.append("--exercise-cmd-vel")
    if skip_connectivity_check:
        command.append("--skip-connectivity-check")
    if quiet:
        command.append("--quiet")
    return command


def _run_validator(
    role,
    site_path,
    config_path,
    artifact_run,
    no_live_probe=False,
    observe_motion=None,
    exercise_cmd_vel=False,
    skip_connectivity_check=False,
    quiet=False,
):
    command = _validator_command(
        role,
        site_path,
        config_path,
        no_live_probe=no_live_probe,
        observe_motion=observe_motion,
        exercise_cmd_vel=exercise_cmd_vel,
        skip_connectivity_check=skip_connectivity_check,
        quiet=quiet,
    )
    artifact_run.log("$ {}".format(" ".join(command)))
    completed = _run_command_streaming_stderr(
        command,
        cwd=str(repo_root()),
        stream_stderr=not quiet,
    )
    artifact_run.write_text("validator.stdout.txt", completed.stdout)
    artifact_run.write_text("validator.stderr.txt", completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "validator failed")
    report = json.loads(completed.stdout)
    artifact_run.write_json("validation-report.json", report)
    return report


def _run_command_streaming_stderr(command, cwd=None, stream_stderr=True):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_parts = []

    def drain_stderr():
        for line in process.stderr:
            stderr_parts.append(line)
            if stream_stderr:
                sys.stderr.write(line)
                sys.stderr.flush()

    stderr_thread = threading.Thread(target=drain_stderr)
    stderr_thread.daemon = True
    stderr_thread.start()
    stdout = process.stdout.read()
    returncode = process.wait()
    stderr_thread.join()
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout or "",
        "".join(stderr_parts),
    )


def _stderr_progress(quiet=False):
    if quiet:
        return None

    def emit(message):
        print(message, file=sys.stderr, flush=True)

    return emit


def _emit_progress(progress, message):
    if progress:
        progress(message)


def _add_role_config_arguments(parser):
    parser.add_argument("--hostname", default=None, help="Role hostname label to write into the site inventory")
    parser.add_argument("--ssh-host", default=None, help="SSH host or IP for the selected role")
    parser.add_argument("--ssh-user", default=None, help="SSH username for the selected role")
    parser.add_argument("--ssh-port", type=int, default=None, help="SSH port for the selected role")
    parser.add_argument(
        "--ssh-auth-mode",
        choices=["agent", "key", "password"],
        default=None,
        help="SSH auth mode for the selected role",
    )
    parser.add_argument("--ssh-key-path", default=None, help="SSH private key path for key-based auth")
    parser.add_argument("--workspace-dir", default=None, help="Remote workspace directory for the selected role")
    parser.add_argument("--ros-master-uri", default=None, help="ROS master URI for the selected role")
    parser.add_argument("--advertise-host", default=None, help="ROS advertised host or IP for the selected role")
    parser.add_argument("--service-user", default=None, help="Systemd service user; defaults to the SSH user")
    parser.add_argument("--service-group", default=None, help="Systemd service group; defaults to the service user")
    parser.add_argument("--storage-root", default=None, help="Companion storage root; maps/media/events live under it")
    notify_group = parser.add_mutually_exclusive_group()
    notify_group.add_argument(
        "--enable-notify",
        action="store_true",
        help="Enable companion notification capability for missions that require notifications",
    )
    notify_group.add_argument(
        "--disable-notify",
        action="store_true",
        help="Disable companion notification capability",
    )
    parser.add_argument("--notify-webhook-url", default=None, help="Companion webhook URL for mission notifications")
    parser.add_argument("--camera-device", default=None, help="Scout camera device path")
    parser.add_argument("--lidar-device", default=None, help="Scout lidar device path")
    parser.add_argument("--drive-model", choices=["diff", "omni"], default=None, help="Scout drive model for AMCL")
    parser.add_argument("--prompt", action="store_true", help="Prompt for configurable values before continuing")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; use CLI flags or saved site defaults",
    )
    parser.add_argument(
        "--skip-connectivity-check",
        action="store_true",
        help="Skip DNS/TCP/SSH reachability checks for this command",
    )
    parser.add_argument(
        "--write-site",
        dest="write_site",
        action="store_true",
        default=True,
        help="Write the effective site inventory back to disk",
    )
    parser.add_argument(
        "--no-write-site",
        dest="write_site",
        action="store_false",
        help="Do not write the effective site inventory back to disk",
    )


def _blank_role_args():
    return argparse.Namespace(
        hostname=None,
        ssh_host=None,
        ssh_user=None,
        ssh_port=None,
        ssh_auth_mode=None,
        ssh_key_path=None,
        workspace_dir=None,
        ros_master_uri=None,
        advertise_host=None,
        service_user=None,
        service_group=None,
        storage_root=None,
        enable_notify=False,
        disable_notify=False,
        notify_webhook_url=None,
        camera_device=None,
        lidar_device=None,
        drive_model=None,
        prompt=False,
        non_interactive=False,
        write_site=True,
        skip_connectivity_check=False,
    )


def _apply_role_configuration(parser, base_site_config, args, role):
    if getattr(args, "prompt", False) and getattr(args, "non_interactive", False):
        parser.error("--prompt and --non-interactive cannot be used together")

    prompt = prompts_enabled(
        force_prompt=getattr(args, "prompt", False),
        non_interactive=getattr(args, "non_interactive", False),
    )
    configured = configure_role(base_site_config, role, args, prompt=prompt)
    return configured, prompt


def _command_roles(args):
    if args.command == "validate":
        return ["scout", "companion"] if args.role == "system" else [args.role]
    if args.command == "probe":
        return ["scout"]
    if args.command == "run":
        return ["companion"]
    return [args.role]


def _prompt_missing_network_roles(site_config, args, roles):
    prompt = prompts_enabled(
        force_prompt=False,
        non_interactive=getattr(args, "non_interactive", False),
    )
    if not prompt:
        return site_config, False

    updated = site_config
    prompted = False
    for role_name in roles:
        if not role_needs_network_prompt(role_config(updated, role_name)):
            continue
        updated = configure_role(updated, role_name, _blank_role_args(), prompt=True, network_only=True)
        prompted = True
    return updated, prompted


def _fail_connectivity(payload):
    lines = payload.get("errors", [])
    raise ValueError("Connectivity validation failed:\n- {}".format("\n- ".join(lines)))


def _validate_connectivity(site_config, roles, artifact_run, skip=False):
    if skip:
        return
    payload = validate_site_connectivity(
        site_config,
        roles,
        runner=CommandRunner(artifact_run=artifact_run),
    )
    if not payload.get("ok", False):
        _fail_connectivity(payload)


def _write_site_if_requested(site_config, site_path, should_write):
    if should_write:
        write_site_config(site_config, site_path)


def _emit_json(payload, artifact_run, filename):
    redacted_payload = redact_sensitive(payload)
    artifact_run.write_json(filename, redacted_payload)
    print(json.dumps(redacted_payload, indent=2, sort_keys=True))


class _UrllibResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        return None


def _post_json(url, payload, timeout=15):
    if requests is not None:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response

    data = _json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return _UrllibResponse(response.status)


def build_parser():
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="auto-scout")
    parser.add_argument("--site", default=None, help="Path to site inventory YAML")
    parser.add_argument("--config", default=str(DEFAULT_SCOUT_CONFIG), help="Path to scout_config.yaml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    configure_parser = subparsers.add_parser("configure", help="Write or update install/deploy settings")
    configure_parser.add_argument("role", choices=["scout", "companion"])
    _add_role_config_arguments(configure_parser)

    deploy_parser = subparsers.add_parser("deploy", help="Deploy a runtime role")
    deploy_parser.add_argument("role", choices=["scout", "companion"])
    deploy_parser.add_argument("--dry-run", action="store_true")
    _add_role_config_arguments(deploy_parser)

    validate_parser = subparsers.add_parser("validate", help="Run role-aware validation")
    validate_parser.add_argument("role", choices=["scout", "companion", "system"])
    validate_parser.add_argument("--no-live-probe", action="store_true", help="Disable live Scout probing")
    validate_parser.add_argument("--skip-connectivity-check", action="store_true", help="Skip remote connectivity validation")
    validate_parser.add_argument("--quiet", action="store_true", help="Suppress live progress output on stderr")
    validate_parser.add_argument(
        "--observe-motion",
        type=float,
        default=None,
        help="Observe odometry for this many seconds while manually driving the Scout",
    )
    validate_parser.add_argument(
        "--exercise-cmd-vel",
        action="store_true",
        help="Publish a short command on the vendor motion topic during live Scout probing",
    )

    probe_parser = subparsers.add_parser("probe", help="Probe the live Scout ROS surface")
    probe_parser.add_argument("role", choices=["scout"])
    probe_parser.add_argument("--skip-connectivity-check", action="store_true", help="Skip remote connectivity validation")
    probe_parser.add_argument("--quiet", action="store_true", help="Suppress live progress output on stderr")
    probe_parser.add_argument(
        "--observe-motion",
        type=float,
        default=15.0,
        help="Observe odometry for this many seconds while manually driving the Scout",
    )
    probe_parser.add_argument(
        "--exercise-cmd-vel",
        action="store_true",
        help="Publish a short command on the vendor motion topic and verify odometry changes",
    )
    probe_parser.add_argument(
        "--write-site",
        dest="write_site",
        action="store_true",
        default=False,
        help="Write probe suggestions back to the site inventory",
    )
    probe_parser.add_argument(
        "--no-write-site",
        dest="write_site",
        action="store_false",
        help="Do not write probe suggestions back to the site inventory",
    )

    run_parser = subparsers.add_parser("run", help="Run a named mission")
    run_parser.add_argument("mission", choices=["smoke-loop"])
    run_parser.add_argument("--mission-file", default=None, help="Explicit mission YAML path")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--skip-connectivity-check", action="store_true", help="Skip remote connectivity validation")

    notify_parser = subparsers.add_parser("notify", help="Send or test operator notifications")
    notify_subparsers = notify_parser.add_subparsers(dest="notify_command", required=True)
    notify_test_parser = notify_subparsers.add_parser("test", help="Send a Slack incoming-webhook test message")
    notify_test_parser.add_argument(
        "--message",
        default=DEFAULT_TEST_MESSAGE,
        help="Message text for the Slack test notification",
    )

    return parser


def main(argv=None):
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    site_config, site_path = load_site_config(args.site)

    artifact_subject = (
        getattr(args, "role", None)
        or getattr(args, "mission", None)
        or getattr(args, "notify_command", None)
        or "run"
    )
    artifact_name = "{}-{}".format(args.command, artifact_subject)
    artifact_run = ArtifactRun(artifact_name)

    if args.command == "configure":
        try:
            configured_site_config, prompted = _apply_role_configuration(parser, site_config, args, args.role)
            _validate_connectivity(
                configured_site_config,
                [args.role],
                artifact_run,
                skip=args.skip_connectivity_check,
            )
            _write_site_if_requested(configured_site_config, site_path, bool(args.write_site))
        except (RuntimeError, ValueError) as exc:
            payload = {
                "ok": False,
                "role": args.role,
                "error": str(exc),
                "site_path": site_path,
                "write_site": bool(args.write_site),
            }
            _emit_json(payload, artifact_run, "configure-report.json")
            return 1

        payload = {
            "ok": True,
            "role": args.role,
            "prompted": prompted,
            "site_path": site_path,
            "write_site": bool(args.write_site),
            "settings": role_config(configured_site_config, args.role),
        }
        _emit_json(payload, artifact_run, "configure-report.json")
        return 0

    if args.command == "deploy":
        original_write_site = args.write_site
        args.write_site = bool(args.write_site and not args.dry_run)
        try:
            effective_site_config, prompted = _apply_role_configuration(parser, site_config, args, args.role)
            _validate_connectivity(
                effective_site_config,
                [args.role],
                artifact_run,
                skip=args.skip_connectivity_check,
            )
            _write_site_if_requested(effective_site_config, site_path, bool(args.write_site))
            if args.role == "scout":
                result = deploy_scout(effective_site_config, artifact_run, dry_run=args.dry_run)
            else:
                result = deploy_companion(effective_site_config, artifact_run, dry_run=args.dry_run)
        except (RuntimeError, ValueError) as exc:
            result = {
                "ok": False,
                "role": args.role,
                "error": str(exc),
                "dry_run": args.dry_run,
            }
            result["prompted"] = False
            result["site_path"] = site_path
            result["write_site"] = bool(original_write_site and not args.dry_run)
            _emit_json(result, artifact_run, "deploy-report.json")
            return 1
        result["prompted"] = prompted
        result["site_path"] = site_path
        result["write_site"] = bool(original_write_site and not args.dry_run)
        _emit_json(result, artifact_run, "deploy-report.json")
        return 0

    if args.command == "validate":
        effective_site_config, prompted = _prompt_missing_network_roles(site_config, args, _command_roles(args))
        if prompted:
            _write_site_if_requested(effective_site_config, site_path, True)
        report = _run_validator(
            args.role,
            site_path,
            args.config,
            artifact_run,
            no_live_probe=args.no_live_probe,
            observe_motion=args.observe_motion,
            exercise_cmd_vel=args.exercise_cmd_vel,
            skip_connectivity_check=args.skip_connectivity_check,
            quiet=args.quiet,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("summary", {}).get("ok", False) else 1

    if args.command == "probe":
        progress = _stderr_progress(args.quiet)
        try:
            effective_site_config, prompted = _prompt_missing_network_roles(site_config, args, ["scout"])
            _emit_progress(progress, "probe: Checking scout connectivity")
            _validate_connectivity(
                effective_site_config,
                ["scout"],
                artifact_run,
                skip=args.skip_connectivity_check,
            )
            _emit_progress(
                progress,
                (
                    "probe: Scout connectivity check skipped"
                    if args.skip_connectivity_check
                    else "probe: Scout connectivity check complete"
                ),
            )
            if prompted:
                _write_site_if_requested(effective_site_config, site_path, True)
            result = probe_scout_capabilities(
                effective_site_config,
                observe_motion_seconds=args.observe_motion,
                exercise_cmd_vel=args.exercise_cmd_vel,
                artifact_run=artifact_run,
                progress=progress,
            )
        except (RuntimeError, ValueError) as exc:
            _emit_progress(progress, "probe: Connectivity or probe setup failed")
            payload = {
                "ok": False,
                "phase": "connectivity",
                "error": str(exc),
                "site_path": site_path,
                "write_site": False,
            }
            _emit_json(payload, artifact_run, "probe-report.json")
            return 1

        if args.write_site:
            updated_site_config = apply_probe_suggestions(effective_site_config, result)
            write_site_config(updated_site_config, site_path)
            result["site_path"] = site_path
            result["write_site"] = True
        else:
            result["site_path"] = site_path
            result["write_site"] = False
        _emit_json(result, artifact_run, "probe-report.json")
        return 0 if result.get("ok", False) else 1

    if args.command == "notify":
        webhook_url = companion_notification_webhook_url(site_config)
        companion = role_config(site_config, "companion")
        if not companion.get("capabilities", {}).get("notify", False):
            payload = {
                "ok": False,
                "phase": "notification_config",
                "error": "Companion notify capability is disabled",
                "site_path": site_path,
            }
            _emit_json(payload, artifact_run, "notify-test-report.json")
            return 1
        if not webhook_url:
            payload = {
                "ok": False,
                "phase": "notification_config",
                "error": "companion.notifications.webhook_url is empty",
                "site_path": site_path,
            }
            _emit_json(payload, artifact_run, "notify-test-report.json")
            return 1

        notification_payload = build_test_notification_payload(args.message)
        try:
            response = _post_json(webhook_url, notification_payload, timeout=15)
        except Exception as exc:
            payload = {
                "ok": False,
                "phase": "notification_delivery",
                "error": str(exc),
                "site_path": site_path,
            }
            _emit_json(payload, artifact_run, "notify-test-report.json")
            return 1

        payload = {
            "ok": True,
            "phase": "notification_delivery",
            "sent": True,
            "status_code": response.status_code,
            "site_path": site_path,
            "message": args.message,
        }
        _emit_json(payload, artifact_run, "notify-test-report.json")
        return 0

    mission_name = "smoke_loop" if args.mission == "smoke-loop" else args.mission
    mission_config, mission_path = load_mission_config(args.mission_file or mission_name)
    try:
        effective_site_config, prompted = _prompt_missing_network_roles(site_config, args, ["companion"])
        _validate_connectivity(
            effective_site_config,
            ["companion"],
            artifact_run,
            skip=args.skip_connectivity_check,
        )
        if prompted:
            _write_site_if_requested(effective_site_config, site_path, True)
        result = run_smoke_loop(
            effective_site_config,
            site_path,
            mission_config,
            mission_path,
            artifact_run,
            dry_run=args.dry_run,
        )
    except (RuntimeError, ValueError) as exc:
        payload = {
            "ok": False,
            "phase": "connectivity",
            "error": str(exc),
            "mission_path": mission_path,
            "site_path": site_path,
            "dry_run": args.dry_run,
        }
        _emit_json(payload, artifact_run, "mission-report.json")
        return 1
    _emit_json(result, artifact_run, "mission-report.json")
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())

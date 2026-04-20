"""Headless CLI for the clean-slate Auto-Scout reset."""

import argparse
import json
import os
import subprocess
import sys

from auto_scout.artifacts import ArtifactRun
from auto_scout.deploy import deploy_companion, deploy_scout
from auto_scout.install_config import configure_role, prompts_enabled
from auto_scout.live_probe import apply_probe_suggestions, probe_scout_capabilities
from auto_scout.mission_config import load_mission_config
from auto_scout.mission_runner import run_smoke_loop
from auto_scout.paths import DEFAULT_SCOUT_CONFIG, repo_root
from auto_scout.site_config import load_site_config, role_config, write_site_config


def _validator_command(role, site_path, config_path, no_live_probe=False, observe_motion=None, exercise_cmd_vel=False):
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
    return command


def _run_validator(role, site_path, config_path, artifact_run, no_live_probe=False, observe_motion=None, exercise_cmd_vel=False):
    command = _validator_command(
        role,
        site_path,
        config_path,
        no_live_probe=no_live_probe,
        observe_motion=observe_motion,
        exercise_cmd_vel=exercise_cmd_vel,
    )
    artifact_run.log("$ {}".format(" ".join(command)))
    completed = subprocess.run(
        command,
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
    )
    artifact_run.write_text("validator.stdout.txt", completed.stdout)
    artifact_run.write_text("validator.stderr.txt", completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "validator failed")
    report = json.loads(completed.stdout)
    artifact_run.write_json("validation-report.json", report)
    return report


def _add_role_config_arguments(parser):
    parser.add_argument("--hostname", default=None, help="Role hostname label to write into the site inventory")
    parser.add_argument("--ssh-host", default=None, help="SSH host or IP for the selected role")
    parser.add_argument("--ssh-user", default=None, help="SSH username for the selected role")
    parser.add_argument("--ssh-port", type=int, default=None, help="SSH port for the selected role")
    parser.add_argument("--workspace-dir", default=None, help="Remote workspace directory for the selected role")
    parser.add_argument("--ros-master-uri", default=None, help="ROS master URI for the selected role")
    parser.add_argument("--advertise-host", default=None, help="ROS advertised host or IP for the selected role")
    parser.add_argument("--service-user", default=None, help="Systemd service user; defaults to the SSH user")
    parser.add_argument("--service-group", default=None, help="Systemd service group; defaults to the service user")
    parser.add_argument("--storage-root", default=None, help="Companion storage root; maps/media/events live under it")
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


def _resolve_site_config(parser, base_site_config, site_path, args, role):
    if getattr(args, "prompt", False) and getattr(args, "non_interactive", False):
        parser.error("--prompt and --non-interactive cannot be used together")

    prompt = prompts_enabled(
        force_prompt=getattr(args, "prompt", False),
        non_interactive=getattr(args, "non_interactive", False),
    )
    configured = configure_role(base_site_config, role, args, prompt=prompt)

    if getattr(args, "write_site", False):
        write_site_config(configured, site_path)

    return configured, prompt


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

    return parser


def main(argv=None):
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    site_config, site_path = load_site_config(args.site)

    artifact_name = "{}-{}".format(args.command, getattr(args, "role", getattr(args, "mission", "run")))
    artifact_run = ArtifactRun(artifact_name)

    if args.command == "configure":
        configured_site_config, prompted = _resolve_site_config(parser, site_config, site_path, args, args.role)
        payload = {
            "ok": True,
            "role": args.role,
            "prompted": prompted,
            "site_path": site_path,
            "write_site": bool(args.write_site),
            "settings": role_config(configured_site_config, args.role),
        }
        artifact_run.write_json("configure-report.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "deploy":
        original_write_site = args.write_site
        args.write_site = bool(args.write_site and not args.dry_run)
        effective_site_config, prompted = _resolve_site_config(parser, site_config, site_path, args, args.role)
        args.write_site = original_write_site
        try:
            if args.role == "scout":
                result = deploy_scout(effective_site_config, artifact_run, dry_run=args.dry_run)
            else:
                result = deploy_companion(effective_site_config, artifact_run, dry_run=args.dry_run)
        except ValueError as exc:
            result = {
                "ok": False,
                "role": args.role,
                "error": str(exc),
                "dry_run": args.dry_run,
            }
            result["prompted"] = prompted
            result["site_path"] = site_path
            result["write_site"] = bool(original_write_site and not args.dry_run)
            artifact_run.write_json("deploy-report.json", result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        result["prompted"] = prompted
        result["site_path"] = site_path
        result["write_site"] = bool(original_write_site and not args.dry_run)
        artifact_run.write_json("deploy-report.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "validate":
        report = _run_validator(
            args.role,
            site_path,
            args.config,
            artifact_run,
            no_live_probe=args.no_live_probe,
            observe_motion=args.observe_motion,
            exercise_cmd_vel=args.exercise_cmd_vel,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("summary", {}).get("ok", False) else 1

    if args.command == "probe":
        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=args.observe_motion,
            exercise_cmd_vel=args.exercise_cmd_vel,
            artifact_run=artifact_run,
        )
        if args.write_site:
            updated_site_config = apply_probe_suggestions(site_config, result)
            write_site_config(updated_site_config, site_path)
            result["site_path"] = site_path
            result["write_site"] = True
        else:
            result["site_path"] = site_path
            result["write_site"] = False
        artifact_run.write_json("probe-report.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok", False) else 1

    mission_name = "smoke_loop" if args.mission == "smoke-loop" else args.mission
    mission_config, mission_path = load_mission_config(args.mission_file or mission_name)
    result = run_smoke_loop(
        site_config,
        site_path,
        mission_config,
        mission_path,
        artifact_run,
        dry_run=args.dry_run,
    )
    artifact_run.write_json("mission-report.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())

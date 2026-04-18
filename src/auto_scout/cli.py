"""Headless CLI for the clean-slate Auto-Scout reset."""

import argparse
import json
import os
import subprocess
import sys

from auto_scout.artifacts import ArtifactRun
from auto_scout.deploy import deploy_companion, deploy_scout
from auto_scout.mission_config import load_mission_config
from auto_scout.mission_runner import run_smoke_loop
from auto_scout.paths import DEFAULT_SCOUT_CONFIG, repo_root
from auto_scout.site_config import load_site_config


def _validator_command(role, site_path, config_path):
    mode = "all" if role == "system" else "runtime"
    return [
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


def _run_validator(role, site_path, config_path, artifact_run):
    command = _validator_command(role, site_path, config_path)
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


def build_parser():
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="auto-scout")
    parser.add_argument("--site", default=None, help="Path to config/site.yaml")
    parser.add_argument("--config", default=str(DEFAULT_SCOUT_CONFIG), help="Path to scout_config.yaml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subparsers.add_parser("deploy", help="Deploy a runtime role")
    deploy_parser.add_argument("role", choices=["scout", "companion"])
    deploy_parser.add_argument("--dry-run", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Run role-aware validation")
    validate_parser.add_argument("role", choices=["scout", "companion", "system"])

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

    if args.command == "deploy":
        if args.role == "scout":
            result = deploy_scout(site_config, artifact_run, dry_run=args.dry_run)
        else:
            result = deploy_companion(site_config, artifact_run, dry_run=args.dry_run)
        artifact_run.write_json("deploy-report.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "validate":
        report = _run_validator(args.role, site_path, args.config, artifact_run)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("summary", {}).get("ok", False) else 1

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

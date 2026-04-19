# Validation Guide

`check_scout_compatibility.py` is now the canonical validation entry point for this repo, and `./auto-scout validate ...` is the supported operator-facing wrapper around it.

For install-time configuration, the supported companion and Scout entrypoints are now `./auto-scout configure scout` and `./auto-scout configure companion`. Those commands can prompt for usernames, SSH targets, workspace directories, and storage roots, or accept them via flags for automation.

It has three modes:

```bash
# Validate repo wiring against the README architecture
python3 check_scout_compatibility.py --mode repo

# Validate the current machine as a Scout, companion, or system role
python3 check_scout_compatibility.py --mode runtime --role scout
python3 check_scout_compatibility.py --mode runtime --role companion
python3 check_scout_compatibility.py --mode all --role system

# Do both and also write a JSON report
python3 check_scout_compatibility.py --mode all --role system --json-out validation-report.json

# Operator-facing wrapper with run artifacts
./auto-scout validate scout
./auto-scout validate companion
./auto-scout validate system
```

## What It Validates

`--mode repo` checks:

- README claims that define the companion-first architecture
- `config/site.yaml` inventory structure and declared capabilities
- `config/missions/smoke_loop.yaml` mission contract
- launch file structure for `scout-runtime` and `companion-runtime`
- service/container files for the reset deployment model
- the companion container contract:
  one host-networked ROS1 companion container with the expected Melodic launch path
- legacy UI and voice quarantine stubs
- mission-critical Python files for syntax and expected entry points

`--mode runtime` checks:

- whether the host looks like a Scout endpoint or a companion computer
- role declarations in `config/site.yaml`
- companion storage directories and container stack expectations
- Scout bridge, motion, camera, and scan capability declarations
- whether live Scout probing matches the declared vendor topics, ROS networking, and capabilities
- mission gating for mapping, patrol, and the `smoke_loop` proof run
- fail-fast blockers like missing pose, missing notify path, or missing vendor bridge declarations

## What Failure Means Right Now

The default repo inventory now reflects one proven rooted Scout for pose and motion, but `./auto-scout probe scout --observe-motion 15` remains the authoritative check before you trust the saved inventory on any real unit.

The most important runtime gate is pose:

- if `roles.scout.capabilities.pose` and `roles.companion.capabilities.pose` are both false, treat that as the primary blocker
- do not switch to Nav2, SLAM Toolbox, or a `ros1_bridge` design while that gate is still failing

The most important runtime sanity check after that is live mismatch detection:

- if live probe contradicts `roles.scout.capabilities.pose`, `roles.scout.capabilities.motion`, `roles.scout.topics.odom`, or `roles.scout.topics.vendor_cmd_vel`, treat that as a real integration failure
- if the cross-host ROS settings still advertise `localhost`, treat that as a deployment bug rather than a hardware limitation

## Probe Workflow

Use probe before deploy or full validation when you have Scout access:

```bash
./auto-scout probe scout --observe-motion 15
./auto-scout probe scout --exercise-cmd-vel
```

Use `--write-site` only when you want to apply the generated site-inventory suggestions automatically:

```bash
./auto-scout probe scout --observe-motion 15 --write-site
```

## Regression Test

The validator's regression coverage lives in:

```bash
python3 -m pytest tests/test_validation_cli.py
```

If `pytest` is not installed in the current environment, the same test module also runs under:

```bash
python3 -m unittest tests/test_validation_cli.py
```

## Retired Scripts

The following scripts were removed because they duplicated or diluted the supported validation path:

- `validate_project.py`
  It was only a wrapper around the canonical validator.
- `scripts/diagnostics.py`
  It preserved an older wrapper CLI instead of testing the real entrypoint.
- `run_tests.py`
  It mixed unrelated syntax, import, and wrapper checks into a second public interface.
- `VALIDATION_SCRIPTS_SUMMARY.md`
  It described an older validation workflow that no longer exists.

- `simple_scout_check.py`
  It only performed shallow environment checks and duplicated compatibility logic.
- `test_basic_hardware.py`
  It focused almost entirely on `/dev/video0` and did not validate the README mission path.
- `test_functionality.py`
  It hard-coded `/home/linaro/catkin_ws/...` paths and encoded older onboard-heavy assumptions.
- `tools/test_scout_modules.py`
  It overlapped heavily with the newer validator and relied on the same fixed Scout deployment paths.
- `tools/validate_configs.py`
  It hard-coded workstation-specific absolute paths and only validated a subset of the architecture.
## Why Consolidate

The removed scripts had three recurring problems:

- they duplicated one another with conflicting outputs
- several assumed an old Scout-only deployment layout instead of the README's companion-first design
- some validated file presence or imports without checking whether the documented missions were actually supportable

Keeping one canonical validator makes it easier to prove what is verified, what is only configured, and what still needs live hardware or ROS evidence.

Every `./auto-scout validate ...` invocation also writes a machine-readable run artifact under `artifacts/runs/`.

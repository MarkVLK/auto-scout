# Validation Guide

`check_scout_compatibility.py` is now the canonical validation entry point for this repo, and `./auto-scout validate ...` is the supported operator-facing wrapper around it.

For install-time configuration, the supported companion and Scout entrypoints are now `./auto-scout configure scout` and `./auto-scout configure companion`. Those commands can prompt for usernames, SSH targets, SSH auth mode, workspace directories, and storage roots, or accept them via flags for automation. By default they save to `config/site_local.yaml` while leaving tracked `config/site.yaml` as the sample inventory.

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

For a full hostname-based system validation from the Mac, the validator checks the
Mac's SSH/ROS reachability and then inspects companion storage and the running
container over SSH on the configured Pi companion host. Do not create
`/srv/auto-scout` on the Mac just to satisfy validation; those runtime
directories belong on the companion.

Before running full validation from the Pi, provision the Pi user's SSH
known-host entries so noninteractive checks can trust both local device
hostnames:

```bash
cd /home/automark/auto-scout
scripts/provision_pi_known_hosts.sh
ssh -o BatchMode=yes linaro@moorebot-scout.local true
ssh -o BatchMode=yes automark@auto-scout-pi5.local true
```

The helper uses `ssh-keyscan` and does not disable SSH host-key checking.
If either batch command fails with `Permission denied` and the Pi's default key
is passphrase-protected, create a dedicated unencrypted Pi-local validation key,
install only its public key into the Scout and Pi `authorized_keys` files, and
select it from the Pi's `~/.ssh/config` for `moorebot-scout.local` and
`auto-scout-pi5.local`.

Smoke-loop notifications are intentionally configured only in
`config/site_local.yaml`. Create a Slack app, enable Incoming Webhooks, add a
webhook to the target channel, and export the generated URL before expecting
the smoke-loop gate to pass:

```bash
export AUTO_SCOUT_NOTIFY_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

```bash
./auto-scout configure companion \
  --non-interactive \
  --skip-connectivity-check \
  --enable-notify \
  --notify-webhook-url "$AUTO_SCOUT_NOTIFY_WEBHOOK_URL"
```

Use `./auto-scout notify test` to verify Slack delivery before relying on
mission notifications. Treat Slack webhook URLs as secrets; Slack documents
that leaked URLs may be revoked. Do not commit them or publish old local
artifacts that include webhook snapshots. The repo ignores
`config/site_local.yaml`, `config/secrets.yaml`, and `artifacts/`, but ignored
files are still your responsibility when sharing logs or archives.

## What It Validates

`--mode repo` checks:

- README claims that define the companion-first architecture
- markdown docs for workstation-only absolute links that break on GitHub
- `config/site.yaml` sample inventory structure and declared capabilities
- `config/missions/smoke_loop.yaml` mission contract
- launch file structure for `scout-runtime` and `companion-runtime`
- Scout built-in sensor topics, battery guard topics, safety settings, and planner-to-safety-filter command routing
- hybrid low-battery return defaults, including the Scout-local guard node, companion map-return controller, and configured dock approach waypoint
- service/container files for the reset deployment model
- persistent Scout swap setup through `auto-scout-scout-swap-setup.service` and the path-escaped systemd `.swap` unit
- the companion container contract:
  one host-networked ROS1 companion container with the expected Melodic launch path
- legacy UI and voice quarantine stubs
- mission-critical Python files for syntax and expected entry points

`--mode runtime` checks:

- whether the host looks like a Scout endpoint or a companion computer
- role declarations in the effective site inventory
- configured hostname resolution, including companion-container lookup of Scout and Pi `.local` names when the container is running
- companion storage directories and container stack expectations
- Scout bridge, motion, camera, scan, ToF, and IMU capability declarations, with scan treated as intentionally disabled when `AUTO_SCOUT_ENABLE_LIDAR=false`
- Scout LiDAR serial-device presence and whether the configured service user can access it when the LD19 runtime is enabled
- Scout memory pressure via `free -m`, `/proc/swaps`, and recent OOM/SIGKILL log lines during live Scout validation
- whether live Scout probing matches the declared vendor topics, normalized sensor topics, battery/dock topics, `/nav_low_bat` service type, ROS networking, and capabilities
- mission gating for mapping, patrol, and the `smoke_loop` proof run
- fail-fast blockers like missing pose, missing notify path, or missing vendor bridge declarations

## What Failure Means Right Now

The default repo inventory now reflects one proven rooted Scout for pose and motion, but `./auto-scout probe scout --observe-motion 15` remains the authoritative check before you trust the saved inventory on any real unit.

The most important runtime gate is pose:

- if `roles.scout.capabilities.pose` and `roles.companion.capabilities.pose` are both false, treat that as the primary blocker
- do not switch to Nav2, SLAM Toolbox, or a `ros1_bridge` design while that gate is still failing

The most important runtime sanity check after that is live mismatch detection:

- if live probe contradicts `roles.scout.devices.lidar`, `roles.scout.capabilities.pose`, `roles.scout.capabilities.motion`, `roles.scout.topics.odom`, or `roles.scout.topics.vendor_cmd_vel`, treat that as a real integration failure
- if live probe cannot see the expected ToF/IMU source or normalized topics, treat that as a built-in sensor integration gap, not as a reason to proceed without LiDAR
- if live probe cannot see `/SensorNode/simple_battery_status`, `/CoreNode/going_home_status`, or `/nav_low_bat`, do not treat low-battery dock return as validated
- if the cross-host ROS settings still advertise `localhost`, treat that as a deployment bug rather than a hardware limitation

For the validated rooted Scout path, a common serial-access failure mode is a LiDAR device owned by `root:dialout` while the configured service user is not in `dialout`. `./auto-scout validate scout` now reports that explicitly.

While the LD19 is detached, the expected state is `AUTO_SCOUT_ENABLE_LIDAR=false` and `AUTO_SCOUT_ENABLE_NAV_STACK=false`. In that mode, validation should report LiDAR serial access, mapping, patrol, and smoke-loop autonomy as skipped by policy rather than failed, while still checking odom, TF, ToF/IMU, battery guard, motion bridge, vendor JPG, and Scout memory pressure when live probing is enabled.

## Probe Workflow

Use probe before deploy or full validation when you have Scout access:

```bash
./auto-scout probe scout --observe-motion 15
./auto-scout probe scout --exercise-cmd-vel
```

The probe reports both vendor source topics such as `/SensorNode/tof` and normalized project topics such as `/scout/tof`, `/scout/imu/data`, `/scout/safety_state`, and `/scout/battery_guard_state`. It also passively checks the `/nav_low_bat` service type; it does not call the docking service.

Use `--write-site` only when you want to apply the generated site-inventory suggestions automatically:

```bash
./auto-scout probe scout --observe-motion 15 --write-site
```

If you run validation with `--no-live-probe`, the Scout serial-access probe is skipped as well.

## Regression Test

The validator's regression coverage lives in:

```bash
python3 -m pytest
```

For focused validation work, run:

```bash
python3 -m pytest tests/test_validation_cli.py tests/test_live_probe.py tests/test_scout_safety_filter.py tests/test_scout_battery_dock_guard.py tests/test_battery_map_return_controller.py
```

If `pytest` is not installed in the current environment, the maintained test modules also run under:

```bash
python3 -m unittest tests.test_validation_cli tests.test_live_probe tests.test_scout_safety_filter tests.test_scout_battery_dock_guard tests.test_battery_map_return_controller
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

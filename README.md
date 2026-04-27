# Auto-Scout

Auto-Scout is a companion-first autonomy project for a Moorebot Scout with an added LD19-class 2D LiDAR. The repository is now documented and structured around what the Scout platform appears to support in practice, not around the earlier assumption that the robot could run a full modern ROS autonomy stack, web UI, voice stack, and ML inference locally.

The clean-slate reset in this repo now treats the runnable system as two explicit roles:

- `scout-runtime`: a thin runtime on the rooted Scout for motion, sensor bridging, battery return-to-dock authority, and health
- `companion-runtime`: the main Raspberry Pi 5 runtime for ROS navigation, storage, validation, low-battery map return, and missions

## Reality Check

As of April 18, 2026, the most relevant public sources say:

- Moorebot's product page lists a quad-core ARM A7 @ 1.2 GHz, 512 MB RAM, Linux + "ROS 1.4", IMU, ToF, 1080p camera, and mecanum wheels, but rooted units can still differ in drivetrain behavior and should be configured from live evidence.
- The Moorebot Scout User Manual V4.0 lists 4 GB eMMC and describes patrol creation as manually driving a path from the dock and saving it.
- Moorebot's FAQ says the onboard flash is 8 GB, user-accessible storage is only about 2 to 3 GB, and there is no SD card slot.
- Moorebot's official open-source repo recommends an Ubuntu 18.04 build environment and exposes a custom `rollereye` Python API plus topics such as `/CoreNode/h264`, `/SensorNode/imu`, and `/SensorNode/tof`.
- ROS REP-3 maps ROS 1 distros to host platforms as follows: Kinetic -> Ubuntu 16.04 / Python 2.7, Melodic -> Ubuntu 18.04 / Python 2.7, Noetic -> Ubuntu 20.04 / Python 3.8.
- Upstream `ros1_bridge` docs say Ubuntu 24.04 is not a supported `ros1_bridge` environment because ROS 1 is not available there.
- Upstream ROS 2 release docs say cross-distribution communication is not guaranteed and should not be relied upon as a supported contract.

That combination means:

- Do not assume ROS Noetic is available on the Scout itself.
- Do not assume the Scout can comfortably run `slam_gmapping`, `move_base`, Flask, speech recognition, and PyTorch at the same time.
- Do not assume local storage is large or consistent enough to be the only place maps and patrol media live.
- Do assume a rooted Scout can still be a useful sensor and motion endpoint if a companion computer handles mapping, planning, storage, and notifications.

Detailed notes and source links live in [docs/VERIFIED_ARCHITECTURE.md](docs/VERIFIED_ARCHITECTURE.md).

## Recommended Architecture

Use two execution tiers:

1. Scout-side runtime

- Keep this lightweight.
- Publish or bridge camera, IMU, ToF, and LD19 scan data.
- Execute motion primitives and media capture.
- Own the low-battery return-to-dock guard and final vendor docking handoff.
- Prefer the Scout's existing vision stack or a thin bridge over heavyweight onboard ML.

2. Companion runtime

- Run Ubuntu 24.04 on the Raspberry Pi 5 host.
- Keep the supported autonomy userspace inside one host-networked ROS1 companion container.
- Prefer Ubuntu 18.04 + ROS Melodic inside that container.
- Fall back to Ubuntu 16.04 + ROS Kinetic only if you must match an older ROS1 environment.
- Run `slam_gmapping`, `map_server`, `amcl`, `move_base`, and optional `explore_lite`.
- When localization is healthy, claim low-battery map return and drive to the configured dock approach waypoint before handing final docking back to Scout.
- Store maps and patrol media here first, then forward to NAS, cloud, or messaging integrations.

This is the only architecture in this repo that currently lines up with the public Scout hardware constraints.

Not recommended for v1:

- a `ros1_bridge`-centered design on Ubuntu 24.04
- mixed ROS 2 distro boundaries such as Humble bridge nodes talking to Jazzy host nodes
- making Nav2, SLAM Toolbox, or continuous companion-side ML inference part of the first hardware bring-up

## Runtime Layout

The supported v1 runtime surface is intentionally headless:

- `auto-scout`
  the main CLI for deploy, validate, and mission runs
- [config/site.yaml](config/site.yaml)
  single inventory for Scout and Raspberry Pi 5 hosts, devices, storage, and declared capabilities
  the shipped sample now reflects one proven rooted Scout, but every real unit should still be probed and compared against hardware
- [config/missions/smoke_loop.yaml](config/missions/smoke_loop.yaml)
  canonical proof mission for a real room loop, return, photo capture, and notification
- `launch/scout_runtime.launch`
  Scout-side launch for the thin bridge runtime, including camera, LD19, ToF, IMU, odometry, low-battery dock guard, safety filtering, and motion normalization
- `launch/companion_runtime.launch`
  companion-side launch for localization or SLAM plus the companion runtime heartbeat and low-battery map-return controller

Legacy browser and voice surfaces are quarantined under [legacy/README.md](legacy/README.md). They are not part of the supported deployment path anymore.

## Validated Scout Path

For the rooted Scout unit validated in the LiDAR bring-up transcript, treat these as the supported Scout-side defaults:

- Scout workspace: `/userdata/catkin_ws/src/auto-scout`
- Scout LiDAR device: `/dev/ttyS4`
- Scout ROS era: Melodic / Python 2.7
- Scout drive model: `diff` for a non-strafing treaded base
- Scout LiDAR bring-up path: the repo's built-in `src/ld19_lidar_driver.py`, launched through `scout_runtime.launch`
- Scout built-in sensor path: vendor ToF and IMU topics are normalized to `/scout/tof` and `/scout/imu/data`
- Scout low-battery path: `scout_battery_dock_guard.py` watches `/SensorNode/simple_battery_status`, publishes `/scout/battery_guard_state`, accepts `/scout/battery_guard_control`, monitors `/CoreNode/going_home_status`, and calls vendor `/nav_low_bat` only when a return-to-dock action is required
- Scout command safety path: `move_base` publishes `/scout/cmd_vel_planner`, `scout_safety_filter.py` gates that command, and `scout_motion_bridge.py` sends only filtered `/scout/cmd_vel_companion` commands to `/cmd_vel_force`

If your rooted Scout can strafe, set `roles.scout.motion.drive_model` to `omni`. Keep `roles.scout.motion.forward_axis` separate from that choice; axis remapping and AMCL motion modeling are different contracts.

Do not treat building upstream C++ LD19 packages on the Scout as the supported baseline for this image. The current repo path is source-only deploy plus the built-in Python serial driver, with live probe and validation used to confirm the real unit still matches the saved inventory.

The built-in ToF and IMU are supporting sensors, not replacements for the LD19. The ToF input is used for close-range caution/stop behavior, IMU is bridged as pose-context data for later validation, and a stale or missing `/scan` still stops normal autonomous command flow.

## Low-Battery Return-To-Dock

Low battery is handled by a hybrid guard:

- The Scout-local `scout_battery_dock_guard.py` is the authority because it runs with `scout_runtime.launch`.
- When battery reaches `safety.min_battery_level`, the guard enters `return_required` and gives the companion up to `safety.map_return_claim_timeout_seconds` to claim map-assisted return.
- The companion `battery_map_return_controller.py` claims only when localization mode is active, `move_base` is available, pose is fresh, and `navigation.dock_approach_waypoint` exists.
- If claimed, the companion cancels normal mission goals, sends `move_base` to the dock approach waypoint, then asks the Scout guard to start vendor final docking.
- If the companion cannot claim, is too slow, or fails, Scout falls back directly to the vendor `/nav_low_bat` routine.
- The final physical docking step is always vendor docking, monitored through `/CoreNode/going_home_status`.

`scout_safety_filter.py` blocks normal planner commands while the guard is in `return_required`, `vendor_docking`, `failed`, or `charging`. It allows planner commands during `map_return` so the companion can drive to the mapped dock approach waypoint.

## Mission Goals

### 1. Autonomous House Mapping

Feasible path:

- Mount and calibrate the LD19 so it has a clean 2D field of view.
- Bridge scan data and a usable pose estimate into a companion ROS1 host.
- Run `slam_gmapping` on the companion.
- Use `map_server` to save maps to companion storage.
- Mirror saved maps to cloud or NAS if desired.

Important caveat:

- `gmapping` needs an odometry or pose source. Moorebot's public docs describe monocular SLAM and VIO, but they do not clearly document a public `/odom` interface. In this repo we treat that as an integration risk that must be solved with a Scout bridge, companion-side odometry, or another exposed pose source.

### 2. Room Patrol With Saved Maps

Feasible path:

- Save one occupancy grid per floor or operating area.
- Define named room goals and a room-to-waypoint graph in YAML.
- Run `amcl` + `move_base` on the companion.
- Let `move_base` command `/scout/cmd_vel_planner`; the Scout-side safety filter publishes the filtered `/scout/cmd_vel_companion`.
- Capture stills or short clips at each patrol goal.
- Persist media to the companion first, then optionally fan out to webhooks or cloud storage.

### 3. Dog Search

Feasible path:

- Reuse the saved map and room graph.
- Search room by room with a bounded timeout.
- Prefer one of these detection paths:
  - a bridge into the Scout's built-in dog recognition if accessible
  - offboard inference on the companion
- When a dog is found, save a photo or short clip plus room metadata, then send or sync it from the companion.

Not recommended:

- PyTorch or other heavyweight local inference on the Scout's 512 MB platform.

## What Changed In This Repo

The repository now assumes:

- companion-first navigation and storage
- Scout-side code should be thin and compatibility-focused
- dog detection should prefer external or built-in Scout signals over local Torch inference
- docs must distinguish verified facts from inference

The repository no longer claims that the stock Scout is a drop-in ROS Noetic robot with enough local resources for a full autonomy stack.

Deployment support is intentionally narrow and now routes through the headless CLI. `tools/deploy.sh` remains as a compatibility wrapper around `./auto-scout deploy scout`.

## Install And Deploy Defaults

The install/deploy path is now designed to be configurable without hand-editing hardcoded usernames and paths.

- Use `./auto-scout configure scout` or `./auto-scout configure companion` to write or update `config/site_local.yaml`
- Pass values such as `--ssh-user`, `--ssh-host`, `--workspace-dir`, `--service-user`, `--storage-root`, or `--drive-model` on the CLI when you already know them
- If you omit those flags in an interactive shell, the CLI prompts you with the current/default value and lets you accept it or replace it
- The tracked `config/site.yaml` file is now a sample inventory; the default saved local inventory lives in `config/site_local.yaml`
- Use `--non-interactive` when you want saved values or explicit flags to be used without prompts
- Use `--skip-connectivity-check` only when you intentionally want to bypass DNS/TCP/SSH validation during offline setup or testing
- The default Scout workspace now points at `/userdata/catkin_ws/src/auto-scout` so the rooted Scout path does not depend on scarce rootfs space
- The default Scout-attached LD19 device now points at `/dev/ttyS4`; use `--lidar-device /dev/ttyUSB0` only when the LiDAR is physically attached somewhere else
- Generated host defaults now use `.invalid` placeholders so a fresh inventory cannot silently deploy against unresolved mDNS assumptions; replace them with real IPs, DNS names, or `.local` values that you know resolve on your network
- For hostname-based setup, put the actual connection names in `ssh.host`, `ros.master_uri`, and `ros.advertise_host`; `roles.*.hostname` is only an inventory label

For example:

```bash
# Write or refresh the companion inventory with prompts
./auto-scout configure companion

# Configure without prompts
./auto-scout configure companion \
  --non-interactive \
  --ssh-host auto-scout-pi5.local \
  --ssh-user automark \
  --workspace-dir /home/automark/auto-scout \
  --ros-master-uri http://moorebot-scout.local:11311 \
  --advertise-host auto-scout-pi5.local \
  --storage-root /srv/auto-scout
```

### Hostname-Based Networking

The recommended local-network setup is mDNS with `moorebot-scout.local` for the Scout and `auto-scout-pi5.local` for the Raspberry Pi companion. Before deploying with those names, verify resolution from every ROS participant:

```bash
# From the operator Mac
ping moorebot-scout.local
ping auto-scout-pi5.local
ssh linaro@moorebot-scout.local
ssh automark@auto-scout-pi5.local

# From the Pi host
getent hosts moorebot-scout.local
getent hosts auto-scout-pi5.local

# From the Scout
getent hosts auto-scout-pi5.local

# From the running companion container
docker exec auto-scout-melodic getent hosts moorebot-scout.local
docker exec auto-scout-melodic getent hosts auto-scout-pi5.local
```

ROS1 uses the advertised hostnames when peers connect back to publishers and subscribers. That means the Scout must also resolve the Pi's advertised hostname, not just the other way around. If mDNS is blocked by the Wi-Fi/router, use router DNS or DHCP hostname registration rather than static `/etc/hosts` entries.

## Validation Order

Treat the bring-up sequence as:

1. Verify the real Scout surface first:
   run `./auto-scout probe scout --observe-motion 15` and decide whether your rooted unit exposes a usable remote ROS graph, only vendor APIs, or a mix
2. Prove scan plus pose:
   until a pose source is declared and tested, neither `move_base` nor Nav2 is the next problem
3. Confirm built-in sensor, battery, and safety topics:
   verify `/scout/tof`, `/scout/imu/data`, `/scout/safety_state`, `/SensorNode/simple_battery_status`, `/scout/battery_guard_state`, `/CoreNode/going_home_status`, and the passive presence/type of `/nav_low_bat`; treat ToF/IMU as safety and context, not LiDAR fallback
4. Start with manual-drive mapping:
   validate `/scan`, `/odom`, TF, and pose inside the companion container, then save and reload a map
5. Add patrol next:
   only after map save/load and localization work
6. Add dog search last:
   as a thin reporting layer on top of a proven map and patrol stack

## Key Files

- [docs/VERIFIED_ARCHITECTURE.md](docs/VERIFIED_ARCHITECTURE.md): verified facts, compatibility matrix, and system design
- [docs/setup_guide.md](docs/setup_guide.md): step-by-step setup for Scout plus companion
- [docs/QUICKSTART.md](docs/QUICKSTART.md): short path to first mapping and patrol tests
- [docs/AUTO_SCOUT_CHECKLIST.md](docs/AUTO_SCOUT_CHECKLIST.md): current hardware and repo checklist for resuming field work
- [config/scout_config.yaml](config/scout_config.yaml): runtime profile, storage policy, and mission settings
- [check_scout_compatibility.py](check_scout_compatibility.py): canonical validator for repo assumptions, runtime readiness, and mission prerequisites
- [config/site.yaml](config/site.yaml): tracked sample inventory for Scout and companion roles
- `config/site_local.yaml`: default saved local inventory written by `./auto-scout configure ...`
- [config/missions/smoke_loop.yaml](config/missions/smoke_loop.yaml): real-world smoke mission contract
- [auto-scout](auto-scout): headless deploy, validate, and mission CLI
- [tools/deploy.sh](tools/deploy.sh): supported Scout deployment entrypoint
- [docs/VALIDATION.md](docs/VALIDATION.md): how to run the validator and why older check scripts were retired

## Repository Directory Listing

This listing covers the maintained tracked project tree and also calls out the local generated directories you will usually see in a working checkout. It intentionally skips `.git`, `__pycache__`, and other interpreter or VCS internals.

```text
.
|-- .gitignore                          # Ignore Python, ROS, build, media, and local override artifacts.
|-- CHANGELOG.md                        # Historical changelog; older entries reflect pre-reset functionality.
|-- CMakeLists.txt                      # Catkin build/install definition for ROS launch files, configs, docs, and Python nodes.
|-- CONTRIBUTING.md                     # Contributor guidance aligned with the companion-first reset.
|-- LICENSE                             # MIT license for the repository.
|-- README.md                           # Primary project overview, architecture notes, and operator guidance.
|-- auto-scout                          # Repo-local Python entrypoint for the headless CLI.
|-- check_scout_compatibility.py        # Canonical validator for repo contracts, runtime assumptions, and mission readiness.
|-- package.xml                         # ROS package manifest and dependency declaration.
|-- requirements.txt                    # Python dependency list for runtime, validation, and tests.
|-- setup.py                            # Python packaging metadata and console-script entrypoint definition.
|-- artifacts/                          # Local artifact root created by CLI runs; ignored by git.
|   `-- runs/                           # Timestamped configure, deploy, validate, and mission output directories.
|-- config/                             # Runtime, inventory, mission, and navigation parameter files.
|   |-- base_local_planner_params.yaml  # TrajectoryPlannerROS tuning for local path execution.
|   |-- costmap_common_params.yaml      # Shared obstacle, footprint, and laser source settings for costmaps.
|   |-- global_costmap_params.yaml      # Global costmap frame and update settings.
|   |-- global_planner_params.yaml      # GlobalPlanner behavior and cost tuning.
|   |-- local_costmap_params.yaml       # Local rolling-window costmap configuration.
|   |-- scout_config.yaml               # Main runtime config covering topics, storage, waypoints, safety, and navigation defaults.
|   |-- site.yaml                       # Tracked sample inventory for Scout and companion roles.
|   |-- site_local.yaml                 # Untracked local inventory written by the configure flow.
|   `-- missions/                       # Mission definitions invoked through the CLI.
|       `-- smoke_loop.yaml             # Proof mission that loops rooms, returns, captures media, and notifies.
|-- container/                          # Companion container build and compose assets.
|   |-- .env.example                    # Example environment variables for direct Docker Compose usage.
|   |-- Dockerfile                      # Ubuntu 18.04 plus ROS Melodic container image for the companion runtime.
|   |-- docker-compose.yml              # Host-networked companion stack definition and launch command.
|   `-- entrypoint.sh                   # Small container entrypoint that sources ROS and execs the requested command.
|-- data/                               # Placeholder for local maps, calibration data, or samples; empty in git.
|-- docs/                               # Supporting architecture, setup, quick-start, and validation guides.
|   |-- AUTO_SCOUT_CHECKLIST.md         # Current hardware, deployment, validation, and mapping checklist.
|   |-- QUICKSTART.md                   # Short path to probe, deploy, map, and validate the supported stack.
|   |-- VALIDATION.md                   # Detailed validator modes, checks, and failure interpretation.
|   |-- VERIFIED_ARCHITECTURE.md        # Verified hardware/software facts and the design conclusions derived from them.
|   `-- setup_guide.md                  # End-to-end Moorebot Scout plus LD19 companion setup guide.
|-- launch/                             # ROS launch entrypoints for Scout and companion roles.
|   |-- companion_runtime.launch        # Selects mapping or localization mode and starts the companion heartbeat plus battery map-return controller.
|   |-- navigation.launch               # Companion localization plus `move_base` stack for saved-map patrols.
|   |-- scout_complete.launch           # Combined bring-up wrapper for optional local Scout bridge plus companion runtime.
|   |-- scout_runtime.launch            # Scout-side bridge launch for heartbeat, lidar, camera, ToF, IMU, battery guard, safety, odom, and motion nodes.
|   `-- slam_mapping.launch             # Companion-side gmapping stack with robot model and transforms.
|-- legacy/                             # Quarantined browser and voice surfaces that are no longer on the supported path.
|   |-- README.md                       # Explains what was retired and where the supported interfaces now live.
|   |-- dashboard.html                  # Old browser dashboard UI asset kept for reference only.
|   |-- scout-web.service               # Legacy systemd unit for the retired web interface.
|   |-- scout_web_interface_legacy.py   # Archived Flask and Socket.IO dashboard implementation.
|   `-- voice_command_interface_legacy.py # Archived speech-recognition control surface.
|-- rviz/                               # RViz visualization presets.
|   `-- scout_navigation.rviz           # RViz workspace for scan, map, robot model, and path visualization.
|-- scripts/                            # Shell entrypoints used by rendered systemd services.
|   |-- start_companion_stack.sh        # Starts or stops the companion Docker Compose stack.
|   `-- start_scout_runtime.sh          # Sources ROS/catkin state and launches the Scout runtime.
|-- src/                                # Python source tree for CLI, runtime nodes, and helpers.
|   |-- __init__.py                     # Top-level package metadata.
|   |-- companion_runtime_agent.py      # Python 2 Scout-compatible companion heartbeat publisher.
|   |-- companion_runtime_support.py    # Python 2 helper functions shared by companion ROS scripts.
|   |-- config_utils.py                 # Thin compatibility wrapper around Scout config loading helpers.
|   |-- battery_map_return_controller.py # Companion node that can claim low-battery map return and drive to the dock approach waypoint.
|   |-- dog_detection_module.py         # External dog-detection event bridge that persists companion-side events.
|   |-- ld19_lidar_driver.py            # ROS driver that reads LD19 packets and publishes `sensor_msgs/LaserScan`.
|   |-- ld19_protocol.py                # Reusable LD19 packet parsing and scan assembly helpers.
|   |-- map_file_guard.py               # Fails localization launch early when the configured map file is missing.
|   |-- scout_camera_driver.py          # Lightweight compressed-image camera bridge for the Scout runtime.
|   |-- scout_battery_dock_guard.py     # Scout-local low-battery guard and vendor `/nav_low_bat` docking handoff.
|   |-- scout_imu_bridge.py             # Normalize the vendor IMU topic to `/scout/imu/data`.
|   |-- scout_motion_bridge.py          # Republish standard autonomy `Twist` commands onto the vendor motion topic.
|   |-- scout_navigation_controller.py  # Python 2 companion-side smoke-loop mission runner.
|   |-- scout_odom_bridge.py            # Normalize vendor odometry into `/odom` plus TF.
|   |-- scout_runtime_agent.py          # Python 2 Scout runtime heartbeat publisher.
|   |-- scout_runtime_config.py         # Python 2-safe site/config loader for Scout-launched nodes.
|   |-- scout_safety_filter.py          # Gate planner velocity commands using ToF, LiDAR heartbeat, and battery guard state.
|   |-- scout_tof_bridge.py             # Normalize the vendor ToF range topic to `/scout/tof`.
|   |-- scout_web_interface.py          # Explicit stub that exits and points users at the retired legacy dashboard.
|   |-- voice_command_interface.py      # Explicit stub that exits and points users at the retired legacy voice path.
|   `-- auto_scout/                     # Python 3 package for the clean-slate CLI and shared runtime logic.
|       |-- __init__.py                 # Package version marker for the clean-slate runtime.
|       |-- artifacts.py                # Helpers for writing timestamped artifact logs and JSON outputs.
|       |-- cli.py                      # Argument parser and command dispatcher for configure, deploy, validate, probe, and run.
|       |-- command_runner.py           # Local, SSH, rsync, and SCP command execution helpers with dry-run support.
|       |-- deploy.py                   # Scout and companion deployment routines plus rendered systemd service templates.
|       |-- install_config.py           # Interactive and flag-driven install/deploy configuration helpers.
|       |-- live_probe.py               # Live Scout topic/device probing and site-inventory reconciliation logic.
|       |-- mission_config.py           # Mission path resolution and YAML loading helpers.
|       |-- mission_runner.py           # Mission gating and remote smoke-loop invocation helpers.
|       |-- paths.py                    # Common repository path constants.
|       |-- site_config.py              # Site inventory defaults, read/write helpers, and role-specific accessors.
|       |-- yaml_loader.py              # YAML load/dump helpers with repo-local fallback parsing.
|       `-- runtime/                    # Python 3 runtime-side helpers that mirror the Python 2 agents/controllers.
|           |-- __init__.py             # Runtime helper package marker.
|           |-- heartbeat.py            # Role-aware Python 3 heartbeat publisher for Scout or companion.
|           `-- mission_controller.py   # Lean Python 3 companion smoke mission controller implementation.
|-- systemd/                            # Example service units; deploy renders role-specific variants from code.
|   |-- auto-scout-companion-runtime.service # Example companion systemd unit.
|   `-- auto-scout-scout-runtime.service # Example Scout systemd unit.
|-- templates/                          # Placeholder for local or legacy template assets; empty in git.
|-- tests/                              # Regression coverage for validator, probing, and LD19 parsing behavior.
|   |-- __init__.py                     # Test package marker.
|   |-- test_ld19_protocol.py           # Unit tests for LD19 packet parsing and scan assembly.
|   |-- test_live_probe.py              # Unit tests for live Scout probing inference and config suggestions.
|   |-- test_battery_map_return_controller.py # Unit tests for companion map-return claim eligibility.
|   |-- test_remote_access.py           # Unit tests for remote connectivity validation helpers.
|   |-- test_scout_battery_dock_guard.py # Unit tests for the low-battery docking guard state machine.
|   |-- test_scout_safety_filter.py     # Unit tests for ToF, scan, and battery-guard command-gating decisions.
|   |-- test_site_config.py             # Unit tests for layered site inventory loading.
|   `-- test_validation_cli.py          # End-to-end regression tests for the validator and CLI contracts.
|-- tools/                              # Compatibility utilities and wrappers used by the runtime and operators.
|   |-- deploy.sh                       # Compatibility shell wrapper around `./auto-scout deploy`.
|   `-- yaml_fallback.py                # Minimal YAML parser used when PyYAML is unavailable.
|-- urdf/                               # Robot description assets.
|   `-- scout.urdf                      # Minimal Scout robot model with base, lidar, camera, ToF, and IMU frames.
`-- validation-report.json              # Local validator JSON output in this checkout; generated and ignored by git.
```

## Suggested Phased Plan

### Phase 1

- Verify root access and topic or API access on the Scout.
- Bring up the LD19, camera, ToF, IMU, low-battery dock guard, safety filter, and Scout-side odom/motion compatibility bridges.
- Confirm `./auto-scout probe scout --observe-motion 15` and `./auto-scout probe scout --exercise-cmd-vel` behave as expected.

### Phase 2

- Stand up a companion computer on the same network.
- Feed scan plus pose into `slam_gmapping`.
- Save and reload a map from companion storage.

### Phase 3

- Add named room goals and patrol sequences.
- Replace `navigation.dock_approach_waypoint: "charging_station"` with a measured pre-dock waypoint after mapping.
- Capture media per room and store it on the companion.
- Add webhook delivery for notifications.

### Phase 4

- Integrate dog detection through either the built-in Scout AI or offboard inference.
- Return room name, timestamp, and media URL/path in the mission result.

## Commands

Use the headless CLI for supported deployment, validation, and smoke-mission workflows:

```bash
# Configure the saved inventory first, or let deploy prompt you interactively
./auto-scout configure scout
./auto-scout configure companion

# Probe the live Scout ROS surface before trusting the saved inventory
./auto-scout probe scout --observe-motion 15

# Deploy the thin Scout runtime
./auto-scout deploy scout

# Deploy the containerized companion runtime
./auto-scout deploy companion

# Validate the rooted Scout, the Raspberry Pi 5 companion, or the full system contract
./auto-scout validate scout
./auto-scout validate companion
./auto-scout validate system

# Run the canonical real-world proof mission
./auto-scout run smoke-loop
```

These lower-level ROS launch commands are still relevant once the companion stack is up:

```bash
roslaunch auto-scout slam_mapping.launch
rosrun map_server map_saver -f /srv/auto-scout/maps/house_map
roslaunch auto-scout navigation.launch map_file:=/srv/auto-scout/maps/house_map.yaml
```

## Current Status

This repo is best treated as:

- a corrected design and integration plan
- a starting point for Scout bridge code and companion-side ROS1 navigation
- a clean-slate headless runtime scaffold centered on `scout-runtime`, `companion-runtime`, `config/site.yaml`, and `config/missions/smoke_loop.yaml`
- not a finished end-to-end autonomy product

## External References

- [Moorebot Scout product page](https://www.moorebot.com/en-ca/products/moorebot-scout)
- [Moorebot Scout FAQ](https://www.moorebot.com/en-ca/pages/faq-for-moorebot-scout-2)
- [Moorebot Scout User Manual V4.0](https://cdn.shopifycdn.net/s/files/1/0016/4616/6103/files/Scout_User_Manual_V4.0.pdf?v=1657247441)
- [Pilot-Labs-Dev/Scout-open-source](https://github.com/Pilot-Labs-Dev/Scout-open-source)
- [ROS REP-3 target platforms](https://www.ros.org/reps/rep-0003.html)

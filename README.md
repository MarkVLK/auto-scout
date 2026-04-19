# Auto-Scout

Auto-Scout is a companion-first autonomy project for a Moorebot Scout with an added LD19-class 2D LiDAR. The repository is now documented and structured around what the Scout platform appears to support in practice, not around the earlier assumption that the robot could run a full modern ROS autonomy stack, web UI, voice stack, and ML inference locally.

The clean-slate reset in this repo now treats the runnable system as two explicit roles:

- `scout-runtime`: a thin runtime on the rooted Scout for motion, sensor bridging, and health
- `companion-runtime`: the main Raspberry Pi 5 runtime for ROS navigation, storage, validation, and missions

## Reality Check

As of April 18, 2026, the most relevant public sources say:

- Moorebot's product page lists a quad-core ARM A7 @ 1.2 GHz, 512 MB RAM, Linux + "ROS 1.4", IMU, ToF, 1080p camera, and mecanum wheels.
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
- Prefer the Scout's existing vision stack or a thin bridge over heavyweight onboard ML.

2. Companion runtime

- Run Ubuntu 24.04 on the Raspberry Pi 5 host.
- Keep the supported autonomy userspace inside one host-networked ROS1 companion container.
- Prefer Ubuntu 18.04 + ROS Melodic inside that container.
- Fall back to Ubuntu 16.04 + ROS Kinetic only if you must match an older ROS1 environment.
- Run `slam_gmapping`, `map_server`, `amcl`, `move_base`, and optional `explore_lite`.
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
  Scout-side launch for the thin bridge runtime, including vendor odometry and motion normalization
- `launch/companion_runtime.launch`
  companion-side launch for localization or SLAM plus the companion runtime heartbeat

Legacy browser and voice surfaces are quarantined under [legacy/README.md](legacy/README.md). They are not part of the supported deployment path anymore.

## Validated Scout Path

For the rooted Scout unit validated in the LiDAR bring-up transcript, treat these as the supported Scout-side defaults:

- Scout workspace: `/userdata/catkin_ws/src/auto-scout`
- Scout LiDAR device: `/dev/ttyS4`
- Scout ROS era: Melodic / Python 2.7
- Scout LiDAR bring-up path: the repo's built-in `src/ld19_lidar_driver.py`, launched through `scout_runtime.launch`

Do not treat building upstream C++ LD19 packages on the Scout as the supported baseline for this image. The current repo path is source-only deploy plus the built-in Python serial driver, with live probe and validation used to confirm the real unit still matches the saved inventory.

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

- Use `./auto-scout configure scout` or `./auto-scout configure companion` to write or update `config/site.yaml`
- Pass values such as `--ssh-user`, `--ssh-host`, `--workspace-dir`, `--service-user`, or `--storage-root` on the CLI when you already know them
- If you omit those flags in an interactive shell, the CLI prompts you with the current/default value and lets you accept it or replace it
- Use `--non-interactive` when you want saved values or explicit flags to be used without prompts
- The default Scout workspace now points at `/userdata/catkin_ws/src/auto-scout` so the rooted Scout path does not depend on scarce rootfs space
- The default Scout-attached LD19 device now points at `/dev/ttyS4`; use `--lidar-device /dev/ttyUSB0` only when the LiDAR is physically attached somewhere else

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
  --storage-root /srv/auto-scout
```

## Validation Order

Treat the bring-up sequence as:

1. Verify the real Scout surface first:
   run `./auto-scout probe scout --observe-motion 15` and decide whether your rooted unit exposes a usable remote ROS graph, only vendor APIs, or a mix
2. Prove scan plus pose:
   until a pose source is declared and tested, neither `move_base` nor Nav2 is the next problem
3. Start with manual-drive mapping:
   validate `/scan`, `/odom`, TF, and pose inside the companion container, then save and reload a map
4. Add patrol next:
   only after map save/load and localization work
5. Add dog search last:
   as a thin reporting layer on top of a proven map and patrol stack

## Key Files

- [docs/VERIFIED_ARCHITECTURE.md](docs/VERIFIED_ARCHITECTURE.md): verified facts, compatibility matrix, and system design
- [docs/setup_guide.md](docs/setup_guide.md): step-by-step setup for Scout plus companion
- [docs/QUICKSTART.md](docs/QUICKSTART.md): short path to first mapping and patrol tests
- [config/scout_config.yaml](config/scout_config.yaml): runtime profile, storage policy, and mission settings
- [check_scout_compatibility.py](check_scout_compatibility.py): canonical validator for repo assumptions, runtime readiness, and mission prerequisites
- [config/site.yaml](config/site.yaml): reset-era inventory for Scout and companion roles
- [config/missions/smoke_loop.yaml](config/missions/smoke_loop.yaml): real-world smoke mission contract
- [auto-scout](auto-scout): headless deploy, validate, and mission CLI
- [tools/deploy.sh](tools/deploy.sh): supported Scout deployment entrypoint
- [docs/VALIDATION.md](docs/VALIDATION.md): how to run the validator and why older check scripts were retired

## Suggested Phased Plan

### Phase 1

- Verify root access and topic or API access on the Scout.
- Bring up the LD19, the camera bridge, and the Scout-side odom/motion compatibility bridges.
- Confirm `./auto-scout probe scout --observe-motion 15` and `./auto-scout probe scout --exercise-cmd-vel` behave as expected.

### Phase 2

- Stand up a companion computer on the same network.
- Feed scan plus pose into `slam_gmapping`.
- Save and reload a map from companion storage.

### Phase 3

- Add named room goals and patrol sequences.
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

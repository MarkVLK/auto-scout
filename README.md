# Auto-Scout

Auto-Scout is a companion-first autonomy project for a Moorebot Scout with an added LD19-class 2D LiDAR. The repository is now documented and structured around what the Scout platform appears to support in practice, not around the earlier assumption that the robot could run a full modern ROS autonomy stack, web UI, voice stack, and ML inference locally.

The clean-slate reset in this repo now treats the runnable system as two explicit roles:

- `scout-runtime`: a thin runtime on the rooted Scout for motion, sensor bridging, and health
- `companion-runtime`: the main Raspberry Pi 5 runtime for ROS navigation, storage, validation, and missions

## Reality Check

As of April 2, 2026, the most relevant public sources say:

- Moorebot's product page lists a quad-core ARM A7 @ 1.2 GHz, 512 MB RAM, Linux + "ROS 1.4", IMU, ToF, 1080p camera, and mecanum wheels.
- The Moorebot Scout User Manual V4.0 lists 4 GB eMMC and describes patrol creation as manually driving a path from the dock and saving it.
- Moorebot's FAQ says the onboard flash is 8 GB, user-accessible storage is only about 2 to 3 GB, and there is no SD card slot.
- Moorebot's official open-source repo recommends an Ubuntu 18.04 build environment and exposes a custom `rollereye` Python API plus topics such as `/CoreNode/h264`, `/SensorNode/imu`, and `/SensorNode/tof`.
- ROS REP-3 maps ROS 1 distros to host platforms as follows: Kinetic -> Ubuntu 16.04 / Python 2.7, Melodic -> Ubuntu 18.04 / Python 2.7, Noetic -> Ubuntu 20.04 / Python 3.8.

That combination means:

- Do not assume ROS Noetic is available on the Scout itself.
- Do not assume the Scout can comfortably run `slam_gmapping`, `move_base`, Flask, speech recognition, and PyTorch at the same time.
- Do not assume local storage is large or consistent enough to be the only place maps and patrol media live.
- Do assume a rooted Scout can still be a useful sensor and motion endpoint if a companion computer handles mapping, planning, storage, and notifications.

Detailed notes and source links live in [docs/VERIFIED_ARCHITECTURE.md](/Users/markvlcek/Code/auto-scout/docs/VERIFIED_ARCHITECTURE.md).

## Recommended Architecture

Use two execution tiers:

1. Scout-side runtime

- Keep this lightweight.
- Publish or bridge camera, IMU, ToF, and LD19 scan data.
- Execute motion primitives and media capture.
- Prefer the Scout's existing vision stack or a thin bridge over heavyweight onboard ML.

2. Companion runtime

- Run on Ubuntu 18.04 + ROS Melodic if you can choose the host.
- Fall back to Ubuntu 16.04 + ROS Kinetic only if you must match an older ROS1 environment.
- Run `slam_gmapping`, `map_server`, `amcl`, `move_base`, and optional `explore_lite`.
- Store maps and patrol media here first, then forward to NAS, cloud, or messaging integrations.

This is the only architecture in this repo that currently lines up with the public Scout hardware constraints.

## Runtime Layout

The supported v1 runtime surface is intentionally headless:

- `auto-scout`
  the main CLI for deploy, validate, and mission runs
- [config/site.yaml](/Users/markvlcek/Code/auto-scout/config/site.yaml)
  single inventory for Scout and Raspberry Pi 5 hosts, devices, storage, and declared capabilities
  keep `pose`, `dock`, and `notify` disabled there until you have verified them on real hardware
- [config/missions/smoke_loop.yaml](/Users/markvlcek/Code/auto-scout/config/missions/smoke_loop.yaml)
  canonical proof mission for a real room loop, return, photo capture, and notification
- `launch/scout_runtime.launch`
  Scout-side launch for the thin bridge runtime
- `launch/companion_runtime.launch`
  companion-side launch for localization or SLAM plus the companion runtime heartbeat

Legacy browser and voice surfaces are quarantined under [legacy/README.md](/Users/markvlcek/Code/auto-scout/legacy/README.md). They are not part of the supported deployment path anymore.

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

## Key Files

- [docs/VERIFIED_ARCHITECTURE.md](/Users/markvlcek/Code/auto-scout/docs/VERIFIED_ARCHITECTURE.md): verified facts, compatibility matrix, and system design
- [docs/setup_guide.md](/Users/markvlcek/Code/auto-scout/docs/setup_guide.md): step-by-step setup for Scout plus companion
- [docs/QUICKSTART.md](/Users/markvlcek/Code/auto-scout/docs/QUICKSTART.md): short path to first mapping and patrol tests
- [config/scout_config.yaml](/Users/markvlcek/Code/auto-scout/config/scout_config.yaml): runtime profile, storage policy, and mission settings
- [check_scout_compatibility.py](/Users/markvlcek/Code/auto-scout/check_scout_compatibility.py): canonical validator for repo assumptions, runtime readiness, and mission prerequisites
- [config/site.yaml](/Users/markvlcek/Code/auto-scout/config/site.yaml): reset-era inventory for Scout and companion roles
- [config/missions/smoke_loop.yaml](/Users/markvlcek/Code/auto-scout/config/missions/smoke_loop.yaml): real-world smoke mission contract
- [auto-scout](/Users/markvlcek/Code/auto-scout/auto-scout): headless deploy, validate, and mission CLI
- [tools/deploy.sh](/Users/markvlcek/Code/auto-scout/tools/deploy.sh): supported Scout deployment entrypoint
- [docs/VALIDATION.md](/Users/markvlcek/Code/auto-scout/docs/VALIDATION.md): how to run the validator and why older check scripts were retired

## Suggested Phased Plan

### Phase 1

- Verify root access and topic or API access on the Scout.
- Bring up the LD19 and camera bridge.
- Confirm you can command motion safely.

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

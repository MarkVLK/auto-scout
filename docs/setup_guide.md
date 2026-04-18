# Moorebot Scout + LD19 Setup Guide

This guide assumes a Moorebot Scout with an added LD19-class 2D LiDAR and a companion computer on the same network. It intentionally does not assume that the Scout can run a full modern ROS autonomy stack by itself.

## 1. Verified Constraints

Before you start, treat these as design constraints:

- The public Moorebot product page lists a quad-core ARM A7 @ 1.2 GHz and 512 MB RAM.
- Official Moorebot materials disagree on flash size: 4 GB in the V4.0 manual, 8 GB in the FAQ, and 16 GB on the current product page.
- The Moorebot FAQ says only about 2 to 3 GB is user-accessible and there is no SD card slot.
- The official Moorebot open-source repo recommends compiling in Ubuntu 18.04 and exposes a custom `rollereye` API plus a few ROS topics.
- ROS Noetic targets Ubuntu 20.04 and Python 3.8, which does not line up with the public Scout environment.

Because of that, this project uses the Scout as a lightweight robot endpoint and moves SLAM, navigation, storage, and notifications to a companion system.

The clean-slate runtime split in this repo is:

- `scout-runtime` on the rooted Scout
- `companion-runtime` on the Raspberry Pi 5
- `auto-scout` as the headless operator CLI
- `config/site.yaml` as the single inventory for both hosts

## 2. Hardware Layout

Recommended layout:

- Scout for locomotion, camera, IMU, ToF, and optional built-in AI
- LD19 mounted high enough to clear the Scout shell and camera mast
- USB-to-TTL adapter or direct serial wiring for the LD19
- Companion computer on the same Wi-Fi network

Recommended companion targets:

- Preferred host: Ubuntu Server 24.04 LTS arm64 on the Raspberry Pi 5
- Preferred ROS userspace: Ubuntu 18.04 + ROS Melodic inside the companion container
- Acceptable fallback: Ubuntu 16.04 + ROS Kinetic
- Not recommended for this repo's current assumptions: trying to force everything onto the Scout itself

## 3. Scout-Side Access

The public Moorebot open-source repo documents a root-enablement path through the mobile app. If you use that route, do it carefully and expect vendor firmware behavior to vary by release.

What you need from the Scout side:

- motion control access
- camera access or video stream access
- IMU and ToF access if available
- a reliable way to start and stop media capture

If the public `rollereye` Python API is available, treat it as the primary Scout control API until you prove a more standard ROS interface exists on your unit.

## 4. LD19 Bring-Up

For the LD19:

- wire power and serial safely
- verify the serial device path on the host that reads the sensor
- publish `/scan`
- confirm a stable frame id and transform to `base_link`

You can publish scan data either:

- directly on the Scout, if serial access is reliable and CPU impact is low
- on the companion, if the LiDAR is physically attached there instead

The repo's launch files now assume that a scan publisher exists and avoid depending on a missing `lidar.launch`.

## 5. Companion ROS1 Stack

Install a ROS1 navigation stack on the companion host.

The supported repo path is now to deploy the companion stack through the container files in `container/` and manage it via `./auto-scout deploy companion`.

Recommended package set:

- `slam_gmapping`
- `map_server`
- `amcl`
- `move_base`
- `dwa_local_planner`
- `global_planner`
- `explore_lite` for autonomous exploration

Why this stack:

- it matches Kinetic and Melodic era tooling
- it is lighter than more modern alternatives
- it is realistic for a Scout-plus-companion architecture

## 6. Pose / Odometry Requirement

This is the main integration risk.

`slam_gmapping` and `move_base` need a usable pose estimate. Moorebot's public docs mention monocular SLAM and VIO, but they do not clearly document a stable public `/odom` contract for rooted users.

You need one of:

- a Scout bridge that exposes pose or odometry from the existing firmware
- a companion-side pose estimate fused from LiDAR, camera, and IMU
- another tested localization source you trust

Do not start full-house autonomous mapping until this piece is solved.

## 7. Storage Policy

Use a conservative storage plan:

- store temporary captures locally on the Scout only when needed
- treat companion storage as the primary store for maps and media
- optionally mirror the companion store to NAS, S3-compatible object storage, or messaging/webhook pipelines

Suggested directories on the companion:

- `/srv/auto-scout/maps`
- `/srv/auto-scout/media`
- `/srv/auto-scout/events`

## 8. Mapping Workflow

1. Bring up the Scout bridge and confirm scan plus pose.
2. Launch SLAM on the companion.
3. If odometry is reliable enough, use `explore_lite` to cover the house.
4. Save the final map on the companion.
5. Record named room goals after the map is stable.

The map should be saved on the companion first, then optionally copied elsewhere.

## 9. Patrol Workflow

For patrol missions:

- load the saved map with `map_server`
- localize with `amcl`
- define one or more room goals
- capture stills or short clips at each goal
- store media on the companion
- optionally send a webhook or messaging notification after the route completes

## 10. Dog Search Workflow

Recommended mission flow:

1. Load the saved map and room graph.
2. Visit each room in a deterministic order.
3. Use either built-in Scout dog detection or offboard inference from the companion.
4. Save a photo or short clip when the dog is found.
5. Return a result containing room name, timestamp, and storage path or URL.

This repo now treats heavyweight local Torch inference as offboard-only unless you prove otherwise on a stronger companion host.

## 11. Headless Workflow

Use these commands as the supported operator flow:

```bash
./auto-scout deploy scout
./auto-scout deploy companion
./auto-scout validate system
./auto-scout run smoke-loop
```

## 12. Source References

- [Moorebot Scout product page](https://www.moorebot.com/en-ca/products/moorebot-scout)
- [Moorebot Scout FAQ](https://www.moorebot.com/en-ca/pages/faq-for-moorebot-scout-2)
- [Moorebot Scout User Manual V4.0](https://cdn.shopifycdn.net/s/files/1/0016/4616/6103/files/Scout_User_Manual_V4.0.pdf?v=1657247441)
- [Pilot-Labs-Dev/Scout-open-source](https://github.com/Pilot-Labs-Dev/Scout-open-source)
- [ROS REP-3 target platforms](https://www.ros.org/reps/rep-0003.html)
- [m-explore / explore_lite](https://index.ros.org/r/m_explore/)

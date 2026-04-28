# Moorebot Scout + LD19 Setup Guide

This guide assumes a Moorebot Scout with an added LD19-class 2D LiDAR and a companion computer on the same network. It intentionally does not assume that the Scout can run a full modern ROS autonomy stack by itself.

## 1. Verified Constraints

Before you start, treat these as design constraints:

- The public Moorebot product page lists a quad-core ARM A7 @ 1.2 GHz and 512 MB RAM.
- Official Moorebot materials disagree on flash size: 4 GB in the V4.0 manual, 8 GB in the FAQ, and 16 GB on the current product page.
- The Moorebot FAQ says only about 2 to 3 GB is user-accessible and there is no SD card slot.
- The official Moorebot open-source repo recommends compiling in Ubuntu 18.04 and exposes a custom `rollereye` API plus a few ROS topics.
- ROS Noetic targets Ubuntu 20.04 and Python 3.8, which does not line up with the public Scout environment.
- The rooted Scout unit validated for this repo exposed Debian 9, ROS Melodic-era tooling, Python 2.7 ROS nodes, `/cmd_vel_force`, `/MotorNode/baselink_odom_relative`, `/MotorNode/vio_odom_relative`, and a free UART at `/dev/ttyS4`.
- Public materials may describe mecanum wheels, but actual rooted units can differ; set `roles.scout.motion.drive_model` from live behavior, not product-page assumptions.

Because of that, this project uses the Scout as a lightweight robot endpoint and moves SLAM, navigation, storage, and notifications to a companion system.

The clean-slate runtime split in this repo is:

- `scout-runtime` on the rooted Scout
- `companion-runtime` on the Raspberry Pi 5
- `auto-scout` as the headless operator CLI
- `config/site.yaml` as the tracked sample inventory for both hosts
- `config/site_local.yaml` as the default saved local inventory written by the CLI

For open-source use, treat `config/site.yaml` as the sample baseline, not the saved live inventory. Use `./auto-scout configure scout` and `./auto-scout configure companion` to write `config/site_local.yaml`, or pass flags such as `--ssh-user`, `--workspace-dir`, and `--storage-root` directly to `configure` or `deploy`.
Generated host defaults now use `.invalid` placeholders so a new inventory fails visibly until you replace them with working DNS or IP values.

## 2. Hardware Layout

Recommended layout:

- Scout for locomotion, camera, IMU, ToF, and optional built-in AI
- LD19 mounted high enough to clear the Scout shell and camera mast
- USB-to-TTL adapter or direct serial wiring for the LD19
- Companion computer on the same Wi-Fi network

Recommended companion targets:

- Preferred host: Ubuntu Server 24.04 LTS arm64 on the Raspberry Pi 5
- Preferred ROS userspace: Ubuntu 18.04 + ROS Melodic inside one host-networked companion container
- Acceptable fallback: Ubuntu 16.04 + ROS Kinetic
- Not recommended for this repo's current assumptions: trying to force everything onto the Scout itself
- Not recommended for v1: a `ros1_bridge` plus ROS2-first design on Ubuntu 24.04

## 3. Scout-Side Access

The public Moorebot open-source repo documents a root-enablement path through the mobile app. If you use that route, do it carefully and expect vendor firmware behavior to vary by release.

What you need from the Scout side:

- motion control access
- camera access or video stream access
- IMU and ToF access if available
- a reliable way to start and stop media capture
- enough writable space outside the root partition for the repo workspace; this repo now defaults the Scout workspace to `/userdata/catkin_ws/src/auto-scout`
- a service user that can open the Scout LiDAR serial device; on the validated unit that meant `linaro` needed `dialout`

If the public `rollereye` Python API is available, treat it as the primary Scout control API until you prove a more standard ROS interface exists on your unit.

Do not assume the first integration step is joining the Scout's ROS master over the network. First prove what your unit actually exposes:

- a usable remote ROS graph
- only vendor APIs
- or a mixed surface where vendor APIs and a few ROS topics coexist

## 4. LD19 Bring-Up

For the LD19:

- wire power and serial safely
- verify the serial device path on the host that reads the sensor
- publish `/scan`
- confirm a stable frame id and transform to `base_link`

The LiDAR mount transform is a calibration input. In this repo, `urdf/scout.urdf` is the operational source of truth for the fixed `base_link` to `base_laser` transform. Measure the physical LD19 position relative to the robot base and update that URDF joint if the mount differs from the checked-in value.

Programmatic calibration is possible in principle, but only with known targets, synchronized sensor data, and established camera, ToF, and LiDAR frame calibration. Treat camera, ToF, and LiDAR comparisons as validation or refinement evidence, not as a reason to automatically rewrite the URDF from casual observations.

For the validated rooted Scout path in this repo:

- the default Scout-attached LD19 device is `/dev/ttyS4`
- the supported Scout-side bring-up path is the repo's built-in `src/ld19_lidar_driver.py`
- Scout deploy is intended to stay source-only; do not treat building upstream C++ LD19 packages on the Scout as the supported baseline for this image
- validate serial access with `./auto-scout validate scout` so missing `dialout` membership shows up as a runtime failure instead of a silent launch problem
- if the Scout already runs an external `ldlidar.service`, stop and disable it before using `scout_runtime.launch` so `/dev/ttyS4` is owned by the repo-managed driver

You can publish scan data either:

- directly on the Scout, if serial access is reliable and CPU impact is low
- on the companion, if the LiDAR is physically attached there instead

The repo's launch files now assume that a scan publisher exists and avoid depending on a missing `lidar.launch`.

If you are attaching the LD19 somewhere other than the Scout UART, override the default with `./auto-scout configure scout --lidar-device ...` or the matching deploy flag.

## 5. Built-In Sensor Bridges And Safety Filter

The Scout runtime now normalizes the built-in ToF and IMU topics before they are used by the rest of the stack:

- `/SensorNode/tof` -> `/scout/tof` as `sensor_msgs/Range`, frame `tof_link`
- `/SensorNode/imu` -> `/scout/imu/data` as `sensor_msgs/Imu`, frame `imu_link`
- `/scout/safety_state` reports the current safety-filter state as JSON text
- `/SensorNode/simple_battery_status` is watched by the Scout-local low-battery dock guard
- `/scout/battery_guard_state` reports the battery guard mode as JSON text
- `/CoreNode/going_home_status` reports vendor docking progress and result

The command path is intentionally split:

- `move_base` publishes raw planner commands to `/scout/cmd_vel_planner`
- `scout_safety_filter.py` watches `/scan` and `/scout/tof`, then publishes approved fresh planner commands to `/scout/cmd_vel_companion`
- `scout_motion_bridge.py` remaps `/scout/cmd_vel_companion` into the vendor `/cmd_vel_force` topic

Configured safety behavior lives under `safety` in `config/scout_config.yaml`. By default, ToF is optional but used when present, close ToF readings slow or stop fresh planner commands, and stale `/scan` stops normal autonomous command flow. With no fresh planner command active, the filter continues publishing `/scout/safety_state` but does not publish periodic zero commands that would interfere with iOS manual driving or vendor docking.

This is not a camera/ToF/IMU navigation fallback. Full mapping and patrol still require a healthy `/scan` plus pose source. The built-in sensors add close-range safety and pose context while preserving the LD19 as the required obstacle/mapping sensor.

## 6. Low-Battery Return-To-Dock

The low-battery behavior is intentionally Scout-authoritative:

- `scout_battery_dock_guard.py` runs on the Scout through `scout_runtime.launch`.
- It triggers when `/SensorNode/simple_battery_status` reports battery at or below `safety.min_battery_level`.
- It publishes `/scout/battery_guard_state` with `mode`, `battery_percent`, `charging`, `reason`, `attempt`, and `active`.
- It accepts companion control messages on `/scout/battery_guard_control`.
- It monitors `/CoreNode/going_home_status` for vendor docking success, failure, cancel, or timeout.
- It calls `/nav_low_bat` only when the guard decides vendor docking should start.

The companion can improve the return path, but it is not required for safety:

- `battery_map_return_controller.py` runs through `companion_runtime.launch`.
- It claims map return only when localization mode is active, `move_base` is available, pose is fresh, and `navigation.dock_approach_waypoint` exists.
- On a valid claim, it cancels normal mission goals, sends `move_base` to the configured dock approach waypoint, then asks the Scout guard to start vendor final docking.
- If it cannot claim, fails, or times out, the Scout guard falls back to vendor `/nav_low_bat`.

The default `navigation.dock_approach_waypoint` is `charging_station` so the config has a stable placeholder. After mapping, replace that with a measured pre-dock waypoint that positions Scout close enough for the vendor docking routine to finish reliably.

Do not run live docking tests until the robot is near the dock, the dock area is clear, and an operator explicitly confirms the test. Passive validation may check that `/SensorNode/simple_battery_status`, `/CoreNode/going_home_status`, and `/nav_low_bat` exist; it must not call `/nav_low_bat`.

## 7. Companion ROS1 Stack

Install a ROS1 navigation stack on the companion host.

The supported repo path is now to deploy the companion stack through the container files in `container/` and manage it via `./auto-scout deploy companion`.

Recommended operator flow:

```bash
# Write companion settings with prompts
./auto-scout configure companion

# Write Scout settings with an explicit non-strafing drive model
./auto-scout configure scout --drive-model diff

# Or set them explicitly without prompts
./auto-scout configure companion \
  --non-interactive \
  --ssh-host auto-scout-pi5.local \
  --ssh-user automark \
  --workspace-dir /home/automark/auto-scout \
  --ros-master-uri http://moorebot-scout.local:11311 \
  --advertise-host auto-scout-pi5.local \
  --storage-root /srv/auto-scout

# Then deploy
./auto-scout deploy companion --non-interactive
```

For mDNS-based networks, use `moorebot-scout.local` as the Scout SSH and ROS host and `auto-scout-pi5.local` as the companion SSH and advertised ROS host. `roles.*.hostname` is only a label; the connection targets are `ssh.host`, `ros.master_uri`, and `ros.advertise_host`.

On each Linux host, publish the intended name and enable mDNS lookup:

```bash
# Scout
sudo hostnamectl set-hostname moorebot-scout
sudo apt-get update
sudo apt-get install -y avahi-daemon libnss-mdns
sudo systemctl enable --now avahi-daemon

# Pi companion
sudo hostnamectl set-hostname auto-scout-pi5
sudo apt-get update
sudo apt-get install -y avahi-daemon libnss-mdns
sudo systemctl enable --now avahi-daemon
```

If `sudo` warns that it cannot resolve the local host after a rename, add a local self-alias such as `127.0.1.1 moorebot-scout` or `127.0.1.1 auto-scout-pi5` to that host's `/etc/hosts`. Do not use `/etc/hosts` for peer device addresses; that would reintroduce stale DHCP state.

Before deploying with `.local` names, verify:

```bash
# Mac/operator machine
ping moorebot-scout.local
ping auto-scout-pi5.local
ssh linaro@moorebot-scout.local
ssh automark@auto-scout-pi5.local

# Pi host
getent hosts moorebot-scout.local
getent hosts auto-scout-pi5.local

# Scout
getent hosts auto-scout-pi5.local

# Companion container after it is started
docker exec auto-scout-melodic getent hosts moorebot-scout.local
docker exec auto-scout-melodic getent hosts auto-scout-pi5.local
```

Container expectations:

- one service: `companion-runtime`
- `network_mode: host`
- ROS1-era autonomy packages inside the container
- mDNS/NSS lookup support for `.local` names
- host Avahi and D-Bus socket mounts so container-side ROS processes can resolve peer `.local` names
- Scout-side motion and sensor integration kept outside the container boundary unless proven otherwise on your unit

For direct `docker compose` usage outside `./auto-scout deploy companion`, copy `container/.env.example` to `container/.env` and replace the placeholder ROS values before you start the service.

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

Do not make these part of the first hardware milestone:

- `ros1_bridge`
- Nav2
- SLAM Toolbox
- continuous YOLO or audio inference on the Pi 5

## 8. Pose / Odometry Requirement

This is the main integration risk.

`slam_gmapping` and `move_base` need a usable pose estimate. Moorebot's public docs mention monocular SLAM and VIO, but they do not clearly document a stable public `/odom` contract for rooted users.

You need one of:

- a Scout bridge that exposes pose or odometry from the existing firmware
- a companion-side pose estimate fused from LiDAR, camera, and IMU
- another tested localization source you trust

Do not start full-house autonomous mapping until this piece is solved.

This is the main reason the repo stays on the ROS1 companion path for v1. Until pose is proven, changing autonomy frameworks adds risk without solving the gating dependency.
Also do not assume `forward_axis` tells you which AMCL odom model to use. `forward_axis` normalizes vendor command axes; `roles.scout.motion.drive_model` selects `diff` vs `omni` motion behavior for localization.
The normalized IMU topic is available for future fusion work, but this repo does not add `robot_localization` or an EKF until real IMU quality is measured.

## 9. Storage Policy

Use a conservative storage plan:

- store temporary captures locally on the Scout only when needed
- treat companion storage as the primary store for maps and media
- optionally mirror the companion store to NAS, S3-compatible object storage, or messaging/webhook pipelines

Suggested directories on the companion:

- `/srv/auto-scout/maps`
- `/srv/auto-scout/media`
- `/srv/auto-scout/events`

If you prefer a different root, set it through `--storage-root`. The deploy path derives `maps`, `media`, and `events` under that root automatically.

## 10. Mapping Workflow

1. Bring up the Scout bridge and confirm scan plus pose.
2. Launch SLAM on the companion.
3. If odometry is reliable enough, use `explore_lite` to cover the house.
4. Save the final map on the companion.
5. Record named room goals after the map is stable.

The map should be saved on the companion first, then optionally copied elsewhere.

## 11. Patrol Workflow

For patrol missions:

- load the saved map with `map_server`
- localize with `amcl`
- define one or more room goals
- replace the default dock approach placeholder with a real mapped pre-dock waypoint
- capture stills or short clips at each goal
- store media on the companion
- optionally send a webhook or messaging notification after the route completes

## 12. Dog Search Workflow

Recommended mission flow:

1. Load the saved map and room graph.
2. Visit each room in a deterministic order.
3. Use either built-in Scout dog detection or offboard inference from the companion.
4. Save a photo or short clip when the dog is found.
5. Return a result containing room name, timestamp, and storage path or URL.

This repo now treats heavyweight local Torch inference as offboard-only unless you prove otherwise on a stronger companion host.

## 13. Headless Workflow

Use these commands as the supported operator flow:

```bash
./auto-scout configure scout
./auto-scout configure companion
./auto-scout deploy scout
./auto-scout deploy companion
./auto-scout validate system
./auto-scout run smoke-loop
```

Before expecting `validate system` to pass from the Pi itself, seed
`automark`'s SSH known-host file for the two `.local` device names:

```bash
cd /home/automark/auto-scout
scripts/provision_pi_known_hosts.sh
ssh -o BatchMode=yes linaro@moorebot-scout.local true
ssh -o BatchMode=yes automark@auto-scout-pi5.local true
```

If those batch SSH checks fail because the Pi's default key is
passphrase-protected, use a separate Pi-local validation key and host-specific
`~/.ssh/config` entries instead of disabling host-key checks.

Before expecting `run smoke-loop` to pass, keep the real webhook URL in the
untracked site inventory and enable the companion notification capability:

```bash
./auto-scout configure companion \
  --non-interactive \
  --skip-connectivity-check \
  --enable-notify \
  --notify-webhook-url "$AUTO_SCOUT_NOTIFY_WEBHOOK_URL"
```

## 14. Source References

- [Moorebot Scout product page](https://www.moorebot.com/en-ca/products/moorebot-scout)
- [Moorebot Scout FAQ](https://www.moorebot.com/en-ca/pages/faq-for-moorebot-scout-2)
- [Moorebot Scout User Manual V4.0](https://cdn.shopifycdn.net/s/files/1/0016/4616/6103/files/Scout_User_Manual_V4.0.pdf?v=1657247441)
- [Pilot-Labs-Dev/Scout-open-source](https://github.com/Pilot-Labs-Dev/Scout-open-source)
- [ROS REP-3 target platforms](https://www.ros.org/reps/rep-0003.html)
- [m-explore / explore_lite](https://index.ros.org/r/m_explore/)

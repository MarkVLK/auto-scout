# Quick Start

This quick start is for the realistic target architecture:

- Scout runs lightweight bridge or capture code
- companion computer runs one host-networked ROS1 companion container for SLAM, navigation, storage, and notifications
- the supported operator surface is the headless `auto-scout` CLI

## 1. Confirm The Platform

Before you deploy, either:

- run `./auto-scout configure scout` and `./auto-scout configure companion`, or
- pass the install values directly on `deploy` with flags such as `--ssh-user`, `--workspace-dir`, and `--storage-root`

In an interactive shell, `configure` and `deploy` now prompt for missing install values so you can accept sane defaults or replace them without editing YAML manually.

Start with the role-aware validator from this repo:

```bash
./auto-scout probe scout --observe-motion 15
./auto-scout validate scout
./auto-scout validate companion
./auto-scout validate system
```

Before you expect runtime validation or `./auto-scout run smoke-loop` to pass, make sure `config/site_local.yaml` reflects what is actually proven on your Scout and Raspberry Pi 5. The tracked [config/site.yaml](../config/site.yaml) file is only the sample baseline.

For the smoke-loop notification gate, use a Slack app incoming webhook and keep the real URL out of tracked config:

1. Create a Slack app in the Slack workspace you manage.
2. Enable **Incoming Webhooks** for the app.
3. Add a webhook to the channel where Auto-Scout should post.
4. Store the generated URL only in your shell or ignored local inventory:

```bash
export AUTO_SCOUT_NOTIFY_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

Write it to `config/site_local.yaml`, which is ignored by git:

```bash
./auto-scout configure companion \
  --non-interactive \
  --skip-connectivity-check \
  --enable-notify \
  --notify-webhook-url "$AUTO_SCOUT_NOTIFY_WEBHOOK_URL"
```

Then send a one-off test message:

```bash
./auto-scout notify test
```

Slack webhook URLs are secrets, and Slack documents that leaked URLs may be revoked. Do not commit them, paste them into issues, or publish local artifacts that captured old webhook snapshots. `config/site_local.yaml`, `config/secrets.yaml`, and `artifacts/` are ignored by this repo for that reason.

If you run full system validation from the Pi, provision SSH known hosts first:

```bash
cd /home/automark/auto-scout
scripts/provision_pi_known_hosts.sh
```

Pay attention to:

- whether `config/site_local.yaml` matches the real Scout and Raspberry Pi 5 targets
- whether hostname targets such as `moorebot-scout.local` and `auto-scout-pi5.local` resolve from the Mac, Pi host, Scout, and companion container before they are used as ROS endpoints
- whether pose, motion, notify, and dock capabilities are declared correctly
- whether the Scout probe found the expected vendor odometry and motion topics
- whether the Scout probe can passively see the battery status topic, battery guard state topic, vendor dock status topic, and `/nav_low_bat` service type
- while the LD19 is detached, whether LiDAR serial access, mapping, patrol, and smoke-loop autonomy are reported as intentional `SKIP` checks instead of launch failures
- during live Scout validation, whether `/userdata/auto-scout/auto-scout.swap` appears in `/proc/swaps` and recent OOM/SIGKILL log checks are clean

If you only want to validate the repo wiring without probing the current machine, use:

```bash
python3 check_scout_compatibility.py --mode repo
```

## 2. Bring Up Sensors

Before touching autonomy:

- confirm what the Scout really exposes: vendor APIs, a remotely reachable ROS graph, or a mix
- confirm vendor `/CoreNode/jpg` is visible and that the companion `vendor_jpg_bridge.py` republishes frames on `/camera/image_raw/compressed`
- while the LD19 is detached, keep `AUTO_SCOUT_ENABLE_LIDAR=false` and `AUTO_SCOUT_ENABLE_NAV_STACK=false`; after the mount/harness is installed, re-enable them and confirm the LD19 publishes `/scan`
- confirm vendor ToF and IMU are normalized to `/scout/tof` and `/scout/imu/data`
- confirm `/scout/safety_state` is being published by `scout_safety_filter.py`
- confirm `/scout/battery_guard_state` is being published by `scout_battery_dock_guard.py`
- confirm `/SensorNode/simple_battery_status`, `/CoreNode/going_home_status`, and `/nav_low_bat` are visible passively before any live docking test
- verify the actual LD19 mounting offset from `base_link` to `base_laser` before mapping; `urdf/scout.urdf` is the source of truth for that transform
- on the validated rooted Scout path, keep the Scout workspace under `/userdata/catkin_ws/src/auto-scout`
- on the validated rooted Scout path, treat `/dev/ttyS4` as the default Scout-attached LD19 device
- use the repo's built-in `ld19_lidar_driver.py` as the supported Scout-side LD19 path; do not treat building upstream C++ LD19 packages on the Scout as the baseline bring-up
- if the Scout still has an older external `ldlidar.service`, stop and disable it before launching the repo-managed Scout runtime so two processes do not fight over `/dev/ttyS4`
- confirm you have a usable pose or odometry source by running `./auto-scout probe scout --observe-motion 15`
- confirm the Scout-side compatibility bridges expose standard `/odom`, `/scout/cmd_vel_planner`, `/scout/cmd_vel_companion`, and `/cmd_vel_force`

If pose is missing, stop here. `slam_gmapping` and `move_base` will not behave well without it.
Do not treat Nav2, SLAM Toolbox, or `ros1_bridge` as the next step while pose is still unproven.
Do not treat camera, ToF, or IMU as a LiDAR fallback for normal autonomy; the current safety filter stops or slows fresh planner commands when ToF is close and stops planner command flow when `/scan` is stale. With no active planner command, `/scout/safety_state` may report a blocked state, but `/scout/cmd_vel_companion` should stay quiet so manual app driving and vendor docking can own the robot.
Charging on the dock is an allowed mission-start state once battery is at or above `safety.mission_start_min_battery_level`; below that, the companion refuses the mission and reports the current battery percentage.
Do not call `/nav_low_bat` during bring-up unless the robot is near the dock and an operator has explicitly confirmed a live docking test.
For proof photos, use vendor `/CoreNode/jpg` through the companion bridge as the normal path. `scout_camera_driver.py` stays disabled by default and is only an opt-in direct `/dev/video0` fallback. Vendor `/CoreNode/h264` remains available for future video work, but smoke-loop still-photo capture does not use it yet.
The companion vendor JPG bridge is lazy: `/CoreNode/jpg` should have no bridge subscriber until a proof-photo preflight or other consumer subscribes to `/camera/image_raw/compressed`.

## 3. Start Mapping On The Companion

Skip this section while the LD19 is detached. The deployed defaults intentionally keep `ld19_lidar_driver`, `slam_gmapping`, `navigation.launch`, and `battery_map_return_controller.py` off until `/scan` is restored.

```bash
./auto-scout configure scout
./auto-scout configure companion
./auto-scout deploy scout
./auto-scout deploy companion
./auto-scout validate system --observe-motion 15
roslaunch auto-scout slam_mapping.launch
```

After the LD19 is mounted and `/scan` is validated, set `AUTO_SCOUT_ENABLE_LIDAR=true` on the Scout service and `AUTO_SCOUT_ENABLE_NAV_STACK=true` on the companion service. Leave `AUTO_SCOUT_LOCALIZATION_MODE=false` for first bring-up, save a map to `/srv/auto-scout/maps/house_map.yaml`, then switch `AUTO_SCOUT_LOCALIZATION_MODE=true` only after that file exists.

If you have reliable scan plus pose, you can:

- drive manually at first, or
- add `explore_lite` once you trust localization enough for unattended exploration

## 4. Save The Map

Save maps on the companion, not only on the Scout:

```bash
rosrun map_server map_saver -f /srv/auto-scout/maps/house_map
```

## 5. Start Navigation With The Saved Map

```bash
roslaunch auto-scout navigation.launch map_file:=/srv/auto-scout/maps/house_map.yaml
```

`move_base` publishes raw planner output to `/scout/cmd_vel_planner`. The Scout-side safety filter publishes only approved fresh planner commands to `/scout/cmd_vel_companion`, which `scout_motion_bridge.py` remaps to `/cmd_vel_force`. If no planner is running, `/scout/cmd_vel_companion` should not emit periodic zero commands.

Then define room goals in [config/scout_config.yaml](../config/scout_config.yaml).

After the map is reliable, replace the default `navigation.dock_approach_waypoint: "charging_station"` with a measured pre-dock waypoint. During low battery, the Scout-local guard gives the companion a short window to claim map return, drive to that approach waypoint, and then hand final docking back to the vendor `/nav_low_bat` routine. If the companion stack is unavailable or fails, Scout falls back directly to vendor docking.

## 6. Patrol Rooms

Recommended patrol flow:

- localize with `amcl`
- move room to room with `move_base`
- keep the Scout-local battery guard running; low battery overrides normal patrol
- capture a still or short clip at each room
- store media on the companion
- optionally push a webhook after the patrol finishes

When you are ready for a real proof run, use:

```bash
export AUTO_SCOUT_ENABLE_NAV_STACK=true
./auto-scout run smoke-loop
```

Without that explicit opt-in, `./auto-scout run smoke-loop` refuses during preflight with `nav_stack_disabled`.

## 7. Dog Search

Recommended dog-search flow:

- reuse the saved map and room graph
- search rooms in a fixed order
- use built-in Scout dog recognition if you can bridge it, otherwise run inference on the companion
- save a photo or short clip when a match is confirmed
- publish room name plus media path or URL

## 8. Do Not Assume

Do not assume any of these are true without proving them on your unit:

- ROS Noetic on the Scout
- `ros1_bridge` on Ubuntu 24.04 as the supported first integration path
- mixed ROS 2 distro communication as a stable system boundary
- enough local Scout storage for long-term map and video retention
- onboard PyTorch inference
- fully documented public `/odom` or `move_base` interfaces from stock Moorebot firmware

## More Detail

- [README.md](../README.md)
- [docs/VALIDATION.md](VALIDATION.md)
- [docs/setup_guide.md](setup_guide.md)
- [docs/VERIFIED_ARCHITECTURE.md](VERIFIED_ARCHITECTURE.md)

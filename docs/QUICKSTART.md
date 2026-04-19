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

Before you expect runtime validation or `./auto-scout run smoke-loop` to pass, make sure [config/site.yaml](../config/site.yaml) reflects what is actually proven on your Scout and Raspberry Pi 5. The shipped sample matches one proven rooted Scout, but live probe results still win.

Pay attention to:

- whether `config/site.yaml` matches the real Scout and Raspberry Pi 5 targets
- whether pose, motion, notify, and dock capabilities are declared correctly
- whether the Scout probe found the expected vendor odometry and motion topics
- whether mapping, patrol, and smoke-loop readiness are reported as `PASS`, `WARN`, or `FAIL`

If you only want to validate the repo wiring without probing the current machine, use:

```bash
python3 check_scout_compatibility.py --mode repo
```

## 2. Bring Up Sensors

Before touching autonomy:

- confirm what the Scout really exposes: vendor APIs, a remotely reachable ROS graph, or a mix
- confirm the camera or video bridge works
- confirm the LD19 publishes `/scan`
- on the validated rooted Scout path, keep the Scout workspace under `/userdata/catkin_ws/src/auto-scout`
- on the validated rooted Scout path, treat `/dev/ttyS4` as the default Scout-attached LD19 device
- use the repo's built-in `ld19_lidar_driver.py` as the supported Scout-side LD19 path; do not treat building upstream C++ LD19 packages on the Scout as the baseline bring-up
- confirm you have a usable pose or odometry source by running `./auto-scout probe scout --observe-motion 15`
- confirm the Scout-side compatibility bridges expose standard `/odom` and `/scout/cmd_vel_companion`

If pose is missing, stop here. `slam_gmapping` and `move_base` will not behave well without it.
Do not treat Nav2, SLAM Toolbox, or `ros1_bridge` as the next step while pose is still unproven.

## 3. Start Mapping On The Companion

```bash
./auto-scout configure scout
./auto-scout configure companion
./auto-scout deploy scout
./auto-scout deploy companion
./auto-scout validate system --observe-motion 15
roslaunch auto-scout slam_mapping.launch
```

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

Then define room goals in [config/scout_config.yaml](../config/scout_config.yaml).

## 6. Patrol Rooms

Recommended patrol flow:

- localize with `amcl`
- move room to room with `move_base`
- capture a still or short clip at each room
- store media on the companion
- optionally push a webhook after the patrol finishes

When you are ready for a real proof run, use:

```bash
./auto-scout run smoke-loop
```

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

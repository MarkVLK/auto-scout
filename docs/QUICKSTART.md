# Quick Start

This quick start is for the realistic target architecture:

- Scout runs lightweight bridge or capture code
- companion computer runs ROS1 SLAM, navigation, storage, and notifications
- the supported operator surface is the headless `auto-scout` CLI

## 1. Confirm The Platform

Start with the role-aware validator from this repo:

```bash
./auto-scout validate scout
./auto-scout validate companion
./auto-scout validate system
```

Before you expect runtime validation or `./auto-scout run smoke-loop` to pass, update [config/site.yaml](/Users/markvlcek/Code/auto-scout/config/site.yaml) so `pose`, `dock`, and `notify` reflect what is actually proven on your Scout and Raspberry Pi 5.

Pay attention to:

- whether `config/site.yaml` matches the real Scout and Raspberry Pi 5 targets
- whether pose, notify, and dock capabilities are declared correctly
- whether mapping, patrol, and smoke-loop readiness are reported as `PASS`, `WARN`, or `FAIL`

If you only want to validate the repo wiring without probing the current machine, use:

```bash
python3 check_scout_compatibility.py --mode repo
```

## 2. Bring Up Sensors

Before touching autonomy:

- confirm the camera or video bridge works
- confirm the LD19 publishes `/scan`
- confirm you have a usable pose or odometry source

If pose is missing, stop here. `slam_gmapping` and `move_base` will not behave well without it.

## 3. Start Mapping On The Companion

```bash
./auto-scout deploy scout
./auto-scout deploy companion
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

Then define room goals in [config/scout_config.yaml](/Users/markvlcek/Code/auto-scout/config/scout_config.yaml).

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
- enough local Scout storage for long-term map and video retention
- onboard PyTorch inference
- fully documented public `/odom` or `move_base` interfaces from stock Moorebot firmware

## More Detail

- [README.md](/Users/markvlcek/Code/auto-scout/README.md)
- [docs/VALIDATION.md](/Users/markvlcek/Code/auto-scout/docs/VALIDATION.md)
- [docs/setup_guide.md](/Users/markvlcek/Code/auto-scout/docs/setup_guide.md)
- [docs/VERIFIED_ARCHITECTURE.md](/Users/markvlcek/Code/auto-scout/docs/VERIFIED_ARCHITECTURE.md)

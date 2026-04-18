# Verified Architecture Notes

This document captures what was verified against public Moorebot and ROS sources on April 2, 2026, plus the design decisions that follow from those facts.

## 1. Verified Facts

### Moorebot Scout hardware and software

- Moorebot's product page currently lists:
  - quad-core ARM A7 @ 1.2 GHz
  - 512 MB LPDDR III
  - Linux + "ROS 1.4"
  - camera, microphone, speaker, IMU, ToF, mecanum wheels
- Moorebot's User Manual V4.0 lists:
  - 4 GB eMMC
  - patrol paths created by manually driving the robot and returning to the dock
  - local photo and video capture
  - built-in recognition for people, dogs, and cats
  - Scratch blocks that generate Python code and run on Scout's ROS system
- Moorebot's FAQ says:
  - onboard flash is 8 GB
  - user-accessible storage is about 2 to 3 GB
  - there is no SD card slot
  - media can be saved to an external drive over the local network
- Moorebot's official open-source repo says:
  - build against Ubuntu 18.04
  - Scout exposes a custom `rollereye` Python API
  - public topics include `/CoreNode/h264`, `/SensorNode/imu`, and `/SensorNode/tof`

### ROS distro compatibility

ROS REP-3 says:

- ROS Kinetic targets Ubuntu 16.04 and Python 2.7
- ROS Melodic targets Ubuntu 18.04 and Python 2.7
- ROS Noetic targets Ubuntu 20.04 and Python 3.8

## 2. Key Conclusions

### Conclusion A: "ROS 1.4" is not a usable distro target

The Moorebot product page uses the label "ROS 1.4", which is not a normal ROS1 distro name. The safest interpretation is that the Scout firmware is ROS-based, but not something that should be treated as a stock Noetic, Melodic, or Kinetic install until proven otherwise.

### Conclusion B: full autonomy should not live entirely on the Scout

The combination of 512 MB RAM, uncertain available storage, and an old ROS-era vendor image makes these onboard assumptions unrealistic:

- full-house SLAM plus navigation
- web dashboard plus speech recognition
- heavyweight local ML inference
- large local video retention

### Conclusion C: companion-first is the practical path

The Scout is still useful as:

- the mobile base
- the camera platform
- the dock-aware robot
- a place to run lightweight bridge code

The companion computer should own:

- SLAM
- localization
- path planning
- autonomous exploration
- map storage
- media storage
- notifications and webhooks

## 3. Recommended Architecture

### Scout side

Responsibilities:

- expose motion primitives
- bridge camera and sensor streams
- publish or bridge LD19 scans if the LiDAR is physically attached there
- capture stills and short clips when asked
- optionally surface built-in dog detection or other vendor AI events

Do not rely on Scout-side Torch inference by default.

### Companion side

Recommended baseline:

- Ubuntu 18.04
- ROS Melodic
- `slam_gmapping`
- `map_server`
- `amcl`
- `move_base`
- `explore_lite`

Fallback if needed:

- Ubuntu 16.04
- ROS Kinetic

### Storage and reporting

Primary storage:

- companion local disk

Secondary storage:

- NAS
- S3-compatible object storage
- webhook-triggered delivery to your preferred notification system

Local Scout storage should be treated as a cache, not the source of truth.

## 4. Compatibility Matrix

| Component | Scout Onboard | Companion |
| --- | --- | --- |
| ROS base | Vendor ROS-like environment, possibly Kinetic/Melodic era | Melodic preferred |
| Python expectations | Likely Python 2.7 era APIs, maybe mixed | Python 2.7 for ROS nodes, Python 3 acceptable for non-ROS utilities |
| SLAM | Not recommended | `slam_gmapping` |
| Localization | Not recommended | `amcl` |
| Path planning | Not recommended | `move_base` |
| Autonomous exploration | Not recommended | `explore_lite` |
| Dog detection | Built-in AI bridge if available | Offboard detector if needed |
| Media archive | Temporary only | Primary |

## 5. Goal-by-Goal Design

### Autonomous whole-house mapping

Recommended flow:

1. Solve scan plus pose.
2. Run `slam_gmapping` on the companion.
3. Use `explore_lite` only after you trust localization.
4. Save the finished map on the companion.
5. Version maps per floor or environment.

Important risk:

`gmapping` needs pose or odometry. Moorebot's public docs mention monocular SLAM and VIO, but I did not find a clearly documented public `/odom` interface in the official public materials. That is an inference from the missing documentation, not a confirmed impossibility.

### Patrol each room or selected rooms

Recommended flow:

1. Load map with `map_server`.
2. Localize with `amcl`.
3. Maintain a room graph in YAML.
4. Patrol named room goals.
5. Capture media at each room.
6. Store media on the companion and mirror elsewhere if needed.

### Find the dog

Recommended flow:

1. Reuse the saved map and room graph.
2. Search rooms in deterministic order.
3. Prefer one of:
   - Scout built-in dog recognition bridged into this stack
   - companion-side detector publishing an external detection event
4. Save a photo or short clip plus room metadata.
5. Return or send a structured result.

## 6. Changes Reflected In This Repo

The repo has been updated to reflect these conclusions:

- docs now describe a companion-first ROS1 architecture
- config now includes runtime and storage assumptions
- launch files are less dependent on nonexistent local package wiring
- code comments and compatibility checks now warn against unsupported Scout-side assumptions
- dog detection code now has an external-detection path so the Scout's built-in AI or a companion detector can drive the mission

## 7. Open Risks

- The public Scout materials do not clearly document a public odometry topic for third-party rooted use.
- Docking behavior may still depend on vendor firmware logic that is not fully documented.
- A top-mounted LD19 may see furniture differently than the stock low camera and ToF stack.
- Mecanum wheel slip can hurt localization quality on smooth floors.
- Messaging integrations such as WhatsApp or Signal are likely easier through companion-side webhooks than from the Scout itself.

## 8. Source Links

- [Moorebot Scout product page](https://www.moorebot.com/en-ca/products/moorebot-scout)
- [Moorebot Scout FAQ](https://www.moorebot.com/en-ca/pages/faq-for-moorebot-scout-2)
- [Moorebot Scout User Manual V4.0](https://cdn.shopifycdn.net/s/files/1/0016/4616/6103/files/Scout_User_Manual_V4.0.pdf?v=1657247441)
- [Pilot-Labs-Dev/Scout-open-source](https://github.com/Pilot-Labs-Dev/Scout-open-source)
- [ROS REP-3 target platforms](https://www.ros.org/reps/rep-0003.html)
- [m-explore / explore_lite](https://index.ros.org/r/m_explore/)

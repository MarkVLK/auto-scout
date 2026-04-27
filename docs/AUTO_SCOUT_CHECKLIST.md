# Auto-Scout Project Checklist

Generated after architecture review session: April 2026.
Last Codex update: 2026-04-27.

Reference this when resuming work. Items are ordered by dependency.

---

## Phase 1: Scout-Side Hardening

### Completed
- [x] SSH access confirmed historically: `ssh linaro@192.168.0.199`
- [x] `/dev/ttyS4` confirmed as LD19 UART port at 230400 baud
- [x] `linaro` user confirmed in `dialout`
- [x] `/userdata` ownership fixed to `linaro:linaro`
- [x] Debian Stretch apt sources fixed to `archive.debian.org`
- [x] LD19 wired to Scout UART header: VDD to VDD, GND to GND, LD19-TX to Scout-RX
  - 2026-04-26 result: repo-managed `/scan` is live again from the Scout runtime
  - Permanent physical fixture/mount is still pending
- [x] Historical/manual Python ldlidar node written at `/userdata/ldlidar_node/ldlidar_node.py`
- [x] Historical/manual `/scan` publishing was confirmed at about 10 Hz
- [x] Manual ldlidar systemd service exists at `/etc/systemd/system/ldlidar.service`
- [x] Manual ldlidar systemd service is stopped and disabled
  ```bash
  systemctl show ldlidar.service --property=LoadState,UnitFileState,ActiveState,SubState,FragmentPath,MainPID
  # 2026-04-25 result: loaded, disabled, inactive, dead, MainPID=0
  ```
- [x] Odometry confirmed on `/MotorNode/baselink_odom_relative`
  - 2026-04-25 live validation saw about 9.991 Hz
- [x] External motion control topic confirmed: `/cmd_vel_force`
- [x] Scout coordinate frame confirmed: `linear.y` = forward
- [x] Tracked `config/site.yaml` now intentionally uses `.invalid` placeholders
  - Do not put live private IPs into tracked `config/site.yaml`
  - Write live values to `config/site_local.yaml` with `./auto-scout configure ...`
- [x] Scout mDNS hostname configured as `moorebot-scout.local`
  - 2026-04-25 result: Scout hostname is `moorebot-scout`
  - `avahi-daemon` and `libnss-mdns` installed on Scout
  - `avahi-daemon` is active
  - Scout `/etc/nsswitch.conf` hosts line is `files mdns4_minimal [NOTFOUND=return] dns`
- [x] Repo-managed Scout runtime deployed
  - 2026-04-26 validation: Scout service is installed and the ROS graph includes `/ld19_lidar_driver`, `/scout_motion_bridge`, `/scout_odom_bridge`, and `/scout_runtime_agent`
- [x] Repo-managed `/scan` verified after Scout runtime deploy
  - 2026-04-26 validation: `/scan` is published by `/ld19_lidar_driver` and visible to the companion container
- [x] Normalized `/odom` and companion command input are present
  - 2026-04-26 direct container check saw `/odom`, `/scan`, `/MotorNode/baselink_odom_relative`, and `/scout/cmd_vel_companion`
- [x] Repo support for built-in sensor normalization and command safety filtering added
  - `/SensorNode/tof` normalizes to `/scout/tof`
  - `/SensorNode/imu` normalizes to `/scout/imu/data`
  - `move_base` now commands `/scout/cmd_vel_planner`
  - `scout_safety_filter.py` publishes filtered commands to `/scout/cmd_vel_companion`
  - `/scout/safety_state` reports safety state JSON
- [x] Repo support for hybrid low-battery return-to-dock added
  - `scout_battery_dock_guard.py` runs on the Scout runtime and is the low-battery authority
  - `/SensorNode/simple_battery_status` is the battery source
  - `/scout/battery_guard_state` reports guard mode JSON
  - `/scout/battery_guard_control` lets the companion claim map return or request vendor final docking
  - `/CoreNode/going_home_status` is monitored for vendor docking status
  - `/nav_low_bat` is the vendor final docking service
  - `battery_map_return_controller.py` runs on the companion and claims map return only when localization, `move_base`, fresh pose, and the dock approach waypoint are healthy
  - Do not subscribe to or echo `/CoreNode/backing_up`

### Still To Do on Scout
- [ ] Print/install the permanent LD19 fixture and lock down the LiDAR cabling
  - Keep the LiDAR on Scout UART path `/dev/ttyS4`
  - Add cable strain relief so robot motion cannot shift or unplug the sensor
  - Re-measure the LiDAR pose relative to `base_link` and update `urdf/scout.urdf` if the checked-in `base_laser` transform is wrong

- [ ] During a safe manual-drive window, rerun validation with odometry motion observation
  ```bash
  ./auto-scout validate scout --observe-motion 10
  ```
  2026-04-26 status: `validate system` passes, but live probe still warns that pose was not dynamically confirmed because no manual-drive observation was requested.

- [ ] After redeploying the Scout runtime, verify built-in sensor bridges and safety state live
  ```bash
  rostopic info /scout/tof
  rostopic info /scout/imu/data
  rostopic echo -n 3 /scout/safety_state
  ```
  Confirm `/scout_tof_bridge`, `/scout_imu_bridge`, and `/scout_safety_filter` are present in `rosnode list`.

- [ ] After redeploying the Scout runtime, passively verify battery guard and vendor docking surfaces
  ```bash
  rostopic info /SensorNode/simple_battery_status
  rostopic echo -n 1 /SensorNode/simple_battery_status
  rostopic info /scout/battery_guard_state
  rostopic echo -n 3 /scout/battery_guard_state
  rostopic info /CoreNode/going_home_status
  rosservice type /nav_low_bat
  ```
  Do not call `/nav_low_bat` during passive validation.
  Do not subscribe to `/CoreNode/backing_up`.

---

## Phase 2: Repo Fixes

These review items are complete in the current repo. Keep this section as a reference so another LLM does not re-open stale tasks.

- [x] `CMakeLists.txt`: unused native OpenCV dependency removed
- [x] `container/Dockerfile`: `python-opencv` is installed for `scout_camera_driver.py`
- [x] `config/site.yaml`: `roles.scout.motion.drive_model: diff` is present
- [x] `launch/navigation.launch`: `odom_model_type` is driven by `AUTO_SCOUT_ODOM_MODEL_TYPE`, defaulting to `diff`
- [x] `launch/navigation.launch`: `move_base` output is routed to `/scout/cmd_vel_planner` so Scout-side safety filtering owns the final command gate
- [x] `launch/scout_runtime.launch`: ToF bridge, IMU bridge, and safety filter nodes are part of the Scout runtime
- [x] `src/scout_tof_bridge.py`: vendor `/SensorNode/tof` is normalized to `/scout/tof`
- [x] `src/scout_imu_bridge.py`: vendor `/SensorNode/imu` is normalized to `/scout/imu/data`
- [x] `src/scout_safety_filter.py`: ToF range and `/scan` freshness gate planner velocity commands before the vendor motion bridge
- [x] `src/scout_battery_dock_guard.py`: Scout-local low-battery guard added with vendor `/nav_low_bat` fallback, status monitoring, retry, and failure states
- [x] `src/battery_map_return_controller.py`: companion map-return controller added for low-battery dock approach navigation
- [x] `src/scout_safety_filter.py`: battery guard modes now block normal planner commands except during `map_return`
- [x] `launch/scout_runtime.launch`: battery dock guard is launched with the Scout runtime
- [x] `launch/companion_runtime.launch`: battery map-return controller is launched with the companion runtime
- [x] `config/scout_config.yaml`: battery guard topics, safety defaults, and `navigation.dock_approach_waypoint` added
- [x] `src/auto_scout/live_probe.py`: passive checks added for battery status, battery guard state, vendor dock status, and `/nav_low_bat` service type
- [x] `urdf/scout.urdf`: `tof_link` added, initially colocated with `camera_link` until measured on hardware
- [x] `container/docker-compose.yml`: `AUTO_SCOUT_ODOM_MODEL_TYPE` is threaded into the companion container environment
- [x] `container/.env.example`: required direct Docker Compose variables are documented with placeholders
  ```bash
  AUTO_SCOUT_ROS_MASTER_URI=http://<scout-host-or-ip>:11311
  AUTO_SCOUT_ROS_HOSTNAME=<companion-host-or-ip>
  AUTO_SCOUT_SITE_CONFIG=/opt/catkin_ws/src/auto-scout/config/site_local.yaml
  AUTO_SCOUT_ODOM_MODEL_TYPE=diff
  AUTO_SCOUT_STORAGE_ROOT=/srv/auto-scout
  AUTO_SCOUT_LOCALIZATION_MODE=false
  ```
- [x] `src/scout_runtime_config.py` and `src/auto_scout/site_config.py`: generated defaults use explicit `.invalid` placeholders instead of silent `moorebot-scout.local` fallbacks
- [x] `src/auto_scout/deploy.py`: service rendering fails fast when ROS endpoints are missing or still use generated placeholders
- [x] `src/auto_scout/deploy.py`: companion service rendering carries the configured Scout drive model through `AUTO_SCOUT_ODOM_MODEL_TYPE`
- [x] `container/Dockerfile`: mDNS/NSS support added for `.local` hostname resolution inside the companion image
- [x] `container/docker-compose.yml`: host Avahi and D-Bus sockets mounted so the host resolver can answer mDNS lookups inside the host-networked container
- [x] `container/docker-compose.yml`: container command sources `/opt/catkin_ws/devel/setup.bash` after `catkin_make`
- [x] Scout and companion launch files use a valid default `site_file` expression
- [x] ROS-launched Python entrypoints tolerate ROS remap arguments with `parse_known_args`
- [x] `scout_odom_bridge.py`: twist normalization handles `TwistWithCovariance`
- [x] `check_scout_compatibility.py`: system validation now checks companion storage and container hostname resolution remotely when run from the Mac/operator host
- [x] `./auto-scout configure/deploy companion`: notification flags added for `--enable-notify`, `--disable-notify`, and `--notify-webhook-url`
- [x] `scripts/provision_pi_known_hosts.sh`: helper added for Pi-side SSH known-host setup without disabling host-key checking
- [x] `src/auto_scout/live_probe.py`: live ROS probe commands have bounded timeouts so validation returns a report instead of hanging

### Deferred Investigation
- [ ] Odom pose-frame investigation
  - During first mapping run, watch whether the map looks geometrically correct
  - If the map is sheared or distorted, the pose position axes may need swapping in `scout_odom_bridge.py`
  - 2026-04-26 note: twist normalization was fixed; this deferred item is about full pose/covariance transform correctness during real mapping
  - A correct fix must handle position x/y, orientation quaternion, twist, and both 6x6 covariance matrices
  - Do not apply a position-only swap without the full fix

---

## Phase 3: Pi 5 Setup

### Prerequisites
- [x] Flash Ubuntu Server 24.04 LTS arm64
  - 2026-04-25 verified: Ubuntu `24.04.4 LTS`, architecture `aarch64`
- [x] Confirm Pi 5 is on the same Wi-Fi subnet as Scout
  - 2026-04-25 historical Pi 5 IP: `192.168.0.88`
  - 2026-04-25 historical Scout IP: `192.168.0.199`
- [x] Verify mDNS hostnames before relying on them for ROS networking
  - 2026-04-25 result: `moorebot-scout.local` resolves to `192.168.0.199`
  - 2026-04-26 result: Pi publishes and resolves as `auto-scout-pi5.local`
  - 2026-04-26 result: Scout resolves `auto-scout-pi5.local`
  - 2026-04-26 result: companion container resolves both `moorebot-scout.local` and `auto-scout-pi5.local`
  ```bash
  # From Mac: confirm both devices are reachable by hostname
  ping moorebot-scout.local
  ping auto-scout-pi5.local
  ssh linaro@moorebot-scout.local
  ssh automark@auto-scout-pi5.local

  # From Pi 5: confirm Scout and self hostname resolution
  getent hosts moorebot-scout.local
  getent hosts auto-scout-pi5.local

  # From Scout: confirm the Pi advertised hostname resolves
  getent hosts auto-scout-pi5.local
  ```

### Docker Setup
- [x] Install Docker on Pi 5
  ```bash
  docker --version
  docker compose version
  ```
  2026-04-25 verified: Docker `29.4.1`, Docker Compose `v5.1.3`, `automark` has Docker daemon access.

- [x] Create storage directories
  ```bash
  sudo mkdir -p /srv/auto-scout/{maps,media,events}
  sudo chown -R automark:automark /srv/auto-scout
  ```
  2026-04-25 verified: `/srv/auto-scout/{maps,media,events}` exists and is owned by `automark`.

- [x] Clone the repo
  ```bash
  git clone <repo_url> ~/auto-scout
  cd ~/auto-scout
  ```
  2026-04-26 verified: Pi repo exists at `/home/automark/auto-scout`, deployed commit includes `686fc48`.

- [x] Configure live site inventory on Mac and Pi
  ```bash
  ./auto-scout configure scout --non-interactive ...
  ./auto-scout configure companion --non-interactive ...
  ```
  Use `config/site_local.yaml` or deployment-generated inventory for live hostnames; keep tracked `config/site.yaml` as the sample.
  2026-04-25 result:
  - local `config/site_local.yaml` exists and is ignored by git
  - Pi `/home/automark/auto-scout/config/site_local.yaml` exists and is ignored by git
  - Scout ROS master should be configured as `http://moorebot-scout.local:11311`
  - companion advertised host should be configured as `auto-scout-pi5.local`
  - smoke-loop notification capability and webhook URL are configured in ignored `config/site_local.yaml`; do not copy the real webhook into tracked files

- [x] Provision Pi-side SSH trust and batch auth for full validation
  ```bash
  cd /home/automark/auto-scout
  scripts/provision_pi_known_hosts.sh
  ssh -o BatchMode=yes linaro@moorebot-scout.local true
  ssh -o BatchMode=yes automark@auto-scout-pi5.local true
  ```
  2026-04-26 result:
  - known-host entries exist for both `.local` names
  - Pi default key was passphrase-protected, so a dedicated Pi-local validation key was created and selected via `~/.ssh/config`
  - batch SSH from Pi to Scout and Pi self-SSH both pass

- [x] For direct Docker Compose usage, create `container/.env` from `container/.env.example`
  - 2026-04-25 result: local and Pi `container/.env` files exist and are ignored by git
  - Current values:
    ```bash
    AUTO_SCOUT_ROS_MASTER_URI=http://moorebot-scout.local:11311
    AUTO_SCOUT_ROS_HOSTNAME=auto-scout-pi5.local
    AUTO_SCOUT_SITE_CONFIG=/opt/catkin_ws/src/auto-scout/config/site_local.yaml
    AUTO_SCOUT_ODOM_MODEL_TYPE=diff
    AUTO_SCOUT_STORAGE_ROOT=/srv/auto-scout
    AUTO_SCOUT_LOCALIZATION_MODE=false
    ```

### Container Build
- [x] Build the companion container
  ```bash
  docker compose -f container/docker-compose.yml build
  ```
  2026-04-25 result: build succeeded on Pi 5 in about 8.5 minutes.

- [x] Confirm build succeeds and `catkin_make` completes
  - 2026-04-25 result: image `container-companion-runtime:latest` built successfully, size about `2.61GB`

- [x] Confirm `explore_lite` is installed inside the image
  ```bash
  docker run --rm --entrypoint /bin/bash container-companion-runtime -lc \
    'source /opt/ros/melodic/setup.bash && source /opt/catkin_ws/devel/setup.bash && rospack find explore_lite'
  ```
  2026-04-25 result: `/opt/ros/melodic/share/explore_lite`.

- [x] Confirm `auto-scout` resolves inside the image
  ```bash
  docker run --rm --entrypoint /bin/bash container-companion-runtime -lc \
    'source /opt/ros/melodic/setup.bash && source /opt/catkin_ws/devel/setup.bash && rospack find auto-scout'
  ```
  2026-04-25 result: `/opt/catkin_ws/src/auto-scout`.

### Validation Snapshot
- [x] Local targeted unit test passes
  ```bash
  python3 -m unittest tests.test_validation_cli
  ```
  2026-04-26 result: 20 targeted validation CLI tests passed.
  2026-04-27 local result after built-in sensor safety integration: `PYENV_VERSION=venv313 pytest` passed 39 tests.
  2026-04-27 local result after hybrid low-battery return integration: `python3 -m unittest discover` passed 54 tests; `python3 check_scout_compatibility.py --mode repo --json` passed.

- [x] Mac-side full system validation passes
  ```bash
  ./auto-scout validate system
  ```
  2026-04-26 result:
  - repo checks passed
  - runtime site contract passed using `config/site_local.yaml`
  - Scout and companion remote connectivity passed from the Mac
  - Scout-side peer hostname resolution passed
  - Scout serial access passed
  - companion storage and Docker Compose were checked remotely on the Pi and passed
  - companion container hostname resolution passed
  - smoke-loop gate no longer fails; it warns only that dock return is unavailable and waypoint fallback will be used
  - remaining expected warning: pose was not dynamically confirmed because `--observe-motion` was not used

- [x] Pi-side full system validation passes
  ```bash
  cd /home/automark/auto-scout
  ./auto-scout validate system
  ```
  2026-04-26 result: `summary.ok` true with the same expected warnings as Mac-side validation.

- [x] Smoke-loop dry run passes without moving the robot
  ```bash
  ./auto-scout run smoke-loop --dry-run
  ```
  2026-04-26 result: `ok: true`, `phase: remote_execution`.

### ROS Networking Verification
- [x] Start the container in mapping mode (`AUTO_SCOUT_LOCALIZATION_MODE=false`)
  - 2026-04-26 result: `auto-scout-melodic` is running after deploy
- [x] Confirm `/scan` is visible from inside the container
  ```bash
  docker exec -it auto-scout-melodic rostopic hz /scan
  # Should show about 10 Hz
  ```
  2026-04-26 result: `/scan` is visible from the container; full validation infers scan capability.
- [x] Confirm normalized `/odom` is visible after the Scout runtime is deployed
  ```bash
  docker exec -it auto-scout-melodic rostopic echo /odom -n 3
  ```
  2026-04-26 direct topic check: `/odom` is present.
- [x] Confirm `/scout/cmd_vel_companion` topic exists in the shared ROS graph
  ```bash
  docker exec -it auto-scout-melodic rostopic info /scout/cmd_vel_companion
  ```
  2026-04-26 direct topic check: `/scout/cmd_vel_companion` is present. Do not publish motion commands except in a safe test area.
- [ ] After redeploy, confirm the new planner, safety, and battery guard topics are present
  ```bash
  docker exec -it auto-scout-melodic rostopic info /scout/cmd_vel_planner
  docker exec -it auto-scout-melodic rostopic echo -n 3 /scout/safety_state
  docker exec -it auto-scout-melodic rostopic info /scout/tof
  docker exec -it auto-scout-melodic rostopic info /scout/imu/data
  docker exec -it auto-scout-melodic rostopic info /SensorNode/simple_battery_status
  docker exec -it auto-scout-melodic rostopic echo -n 3 /scout/battery_guard_state
  docker exec -it auto-scout-melodic rostopic info /CoreNode/going_home_status
  docker exec -it auto-scout-melodic rosservice type /nav_low_bat
  ```
  If you run a motion command test, publish to `/scout/cmd_vel_planner` in a safe area so the safety filter remains in the path.
  Do not call `/nav_low_bat` from this validation step.

---

## Phase 4: Mapping

- [x] Deploy full stack
  ```bash
  ./auto-scout deploy scout
  ./auto-scout deploy companion
  ./auto-scout validate system
  ```
  2026-04-26 result: both Mac-side and Pi-side `./auto-scout validate system` pass after deploy.
- [x] Confirm `/scan` is available after deploying the Scout runtime
- [ ] Confirm `/odom` motion dynamically with `--observe-motion` before trusting a map
- [ ] Drive Scout manually around the house while gmapping runs
  - Use the Scout iOS app for manual driving during this phase
  - Drive slowly and avoid doorways on the first pass
  - Cover all rooms you want patrolled
- [ ] Save the map
  ```bash
  docker exec -it auto-scout-melodic \
    rosrun map_server map_saver -f /srv/auto-scout/maps/house_map
  ```
- [ ] Verify map files exist on Pi 5
  ```bash
  ls -la /srv/auto-scout/maps/
  # Should show house_map.pgm and house_map.yaml
  ```
- [ ] Flip to localization mode: set `AUTO_SCOUT_LOCALIZATION_MODE=true` in `.env`
- [ ] Restart companion container and confirm AMCL localizes correctly

---

## Phase 5: Patrol

- [ ] Define real named room waypoints in `config/scout_config.yaml`
- [ ] Replace `navigation.dock_approach_waypoint: "charging_station"` with a measured pre-dock waypoint after mapping
  - Recommended waypoint name after mapping: `pre_dock`
  - It should put the Scout close enough and aligned enough for vendor `/nav_low_bat` to complete the physical dock approach
- [ ] Configure `config/missions/smoke_loop.yaml` with your real room loop
- [x] Resolve the smoke-loop notification blocker
  - 2026-04-26 result: `roles.companion.capabilities.notify` is enabled in ignored live inventory and a webhook URL is configured in `config/site_local.yaml`
  - Keep the real webhook URL out of tracked files
- [x] Run smoke-loop dry run
  ```bash
  ./auto-scout run smoke-loop --dry-run
  ```
  2026-04-26 result: dry run passed with `ok: true`.
- [ ] Run real smoke test mission only after confirming the robot is in a safe area
  ```bash
  ./auto-scout run smoke-loop
  ```
- [ ] Verify photo capture works at each waypoint
- [ ] Store live notification settings in `config/site_local.yaml`, not tracked `config/site.yaml`

### Low-Battery Docking Staging
- [ ] Passive validation only: confirm battery, guard, vendor dock status, and `/nav_low_bat` service type without calling the service
- [ ] Dry-run validation: run `scout_battery_dock_guard.py` with dry-run enabled and simulate low battery in a non-moving test setup
- [ ] Live vendor final docking test near dock
  - Put Scout near the charging dock first
  - Clear the area
  - Confirm `/CoreNode/going_home_status` transitions to success
  - Keep `roles.scout.capabilities.dock: false` until this passes
- [ ] Live mapped dock approach test
  - Start from the mapped pre-dock approach area
  - Confirm companion map return reaches `navigation.dock_approach_waypoint`
  - Confirm the Scout guard then starts vendor final docking
- [ ] Companion-off fallback test
  - Stop the companion map-return controller
  - Confirm the Scout guard falls back to vendor `/nav_low_bat` after `map_return_claim_timeout_seconds`

---

## Phase 6: Dog Detection

- [ ] Confirm the Scout built-in dog detection topic live before documenting it as supported
  - Candidate from previous notes: `/CloudNode/dog_monitor`
  - Current repo bridge topic: `/scout/dog_detection_external`
- [ ] If using Scout built-in detection, map the confirmed built-in topic into `/scout/dog_detection_external`
- [ ] If using offboard inference, add companion-side detection after patrol is stable
- [ ] Integrate detection result into mission loop
- [ ] Return room name, timestamp, and photo path in mission result

---

## Key Reference: Verified Scout ROS Interface

| Capability | Topic | Current Status |
|---|---|---|
| LiDAR scan | `/scan` | Live 2026-04-26 from repo-managed `/ld19_lidar_driver`; visible from companion container |
| Odometry | `/MotorNode/baselink_odom_relative` | Live 2026-04-26 at about 10 Hz while stationary; rerun with `--observe-motion` during safe manual driving |
| Odometry normalized | `/odom` | Present 2026-04-26 after repo Scout runtime deploy |
| Motion control | `/cmd_vel_force` | Live topic confirmed; overrides internal nav stack; Scout forward axis is `linear.y` |
| Motion planner input | `/scout/cmd_vel_planner` | Raw `move_base` output; safety filter input after latest repo changes |
| Motion control companion input | `/scout/cmd_vel_companion` | Safety-filtered command; `scout_motion_bridge.py` remaps to `/cmd_vel_force` |
| Safety state | `/scout/safety_state` | JSON state from `scout_safety_filter.py`; verify after redeploy |
| Battery status source | `/SensorNode/simple_battery_status` | Vendor `roller_eye/status`; status index 1 is battery percent and index 2 is charging flag |
| Battery guard state | `/scout/battery_guard_state` | JSON mode from `scout_battery_dock_guard.py`; verify after redeploy |
| Battery guard control | `/scout/battery_guard_control` | Companion control channel for map-return claim, vendor dock request, and map-return failure |
| Vendor dock status | `/CoreNode/going_home_status` | Vendor docking state; success is reported by vendor status code 4 |
| Vendor low-battery dock service | `/nav_low_bat` | Final physical docking routine; verify type passively before live test |
| Dangerous vendor trigger topic | `/CoreNode/backing_up` | Do not subscribe, echo, or use |
| IMU source | `/SensorNode/imu` | Available per prior topic inventory; reconfirm during full validation if needed |
| IMU normalized | `/scout/imu/data` | Published by `scout_imu_bridge.py`; verify after redeploy |
| ToF source | `/SensorNode/tof` | Available per prior topic inventory; reconfirm during full validation if needed |
| ToF normalized | `/scout/tof` | Published by `scout_tof_bridge.py`; used by safety filter |
| Camera h264 | `/CoreNode/h264` | Available per prior topic inventory |
| Camera jpg | `/CoreNode/jpg` | Available per prior topic inventory |
| Dog detection | `/scout/dog_detection_external` | Repo bridge topic; confirm any built-in Scout source topic before wiring |

## Key Reference: Network and Access

| Item | Value |
|---|---|
| Scout SSH | `ssh linaro@moorebot-scout.local` |
| Scout root | `sudo su -` from linaro session |
| Scout ROS master | `http://moorebot-scout.local:11311` |
| Historical Scout IP | `192.168.0.199` on 2026-04-25; do not treat as stable DHCP state |
| Scout LiDAR device | `/dev/ttyS4` at 230400 baud |
| Scout LiDAR service state | `ldlidar.service` disabled and inactive as of 2026-04-25 |
| Repo Scout runtime state | deployed and validated as of 2026-04-26 |
| Scout userdata | `/userdata/` owned by `linaro` |
| Companion SSH | `ssh automark@auto-scout-pi5.local` |
| Companion advertised host | `auto-scout-pi5.local` |
| Historical Companion IP | `192.168.0.88` on 2026-04-25; do not treat as stable DHCP state |
| Companion hostname | `auto-scout-pi5.local` |
| Companion storage | `/srv/auto-scout/{maps,media,events}` |
| Companion image | `container-companion-runtime:latest` built and deployed on Pi 5 as of 2026-04-26 |
| Companion container | `auto-scout-melodic` running as of 2026-04-26 |
| Live inventory | `config/site_local.yaml` exists locally and on the Pi; ignored by git |
| Direct Compose env | `container/.env` exists locally and on the Pi; ignored by git |
| Smoke-loop notification | configured in ignored live inventory as of 2026-04-26; real webhook must stay out of tracked files |
| Pi validation SSH | dedicated Pi-local validation key selected via `~/.ssh/config` for `moorebot-scout.local` and `auto-scout-pi5.local` |

## Key Reference: Architecture Decisions and Rationale

- ROS1 Melodic in Docker on Ubuntu 24.04 Pi 5, not ROS2, is the supported v1 path.
- Scout is the ROS master; the companion container points to `http://moorebot-scout.local:11311` once live inventory is configured.
- ROS1 hostnames must resolve bidirectionally: the companion container must resolve `moorebot-scout.local`, and the Scout must resolve `auto-scout-pi5.local`.
- Do not use `/etc/hosts` for peer device addresses; if mDNS is blocked, prefer router DNS or DHCP hostname registration.
- Use `/cmd_vel_force`, not `/cmd_vel`, for external motion control.
- Normal autonomy should publish to `/scout/cmd_vel_planner`; `/cmd_vel_force` is reached only after safety filtering and `scout_motion_bridge.py`.
- Scout forward motion is on `linear.y`; `scout_motion_bridge.py` handles remapping after `/scout/cmd_vel_companion`.
- Built-in ToF and IMU are supporting sensors. They add command safety and pose context, but they are not a replacement for `/scan` during mapping or patrol.
- Low battery overrides normal Auto-Scout work. The Scout-local guard is authoritative and vendor `/nav_low_bat` is always the final physical docking step.
- Companion map return is an optimization only when localization, `move_base`, fresh pose, and the dock approach waypoint are healthy.
- Keep `drive_model: diff` for this unit unless later live testing proves otherwise.
- Do not use `ros1_bridge`, Nav2, or SLAM Toolbox as the next integration step while mapping and dynamic pose validation remain unresolved.

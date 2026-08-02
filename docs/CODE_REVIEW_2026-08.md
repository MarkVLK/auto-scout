# Code Review — August 2026

Review of the repository after roughly three months idle (last commit 2026-05-07).
Scope: architecture soundness, documentation accuracy, bugs, and security.

Nothing in this document has been fixed. It is a findings list, ordered by how much
damage each item does during hardware bring-up.

## Summary

The architecture is sound and does not need rework. The companion-first split, the
Scout-local safety filter and battery guard, the placement of the low-battery authority
on the robot rather than the companion, and the decision to hand final docking back to
vendor firmware are all the right calls for this hardware. The reasoning in
`docs/VERIFIED_ARCHITECTURE.md` still holds up against the constraints it cites.

Security posture is good for a project of this kind: `yaml.safe_load` everywhere, no
`eval`/`exec`/`shell=True` on untrusted input, no `StrictHostKeyChecking=no`, secrets
gitignored, a redaction module that strips webhook URLs from artifacts, and deploy code
that deliberately strips the Slack webhook from the Scout's copy of the inventory. Two
hardening gaps are noted below; neither is remotely exploitable.

Test suite: **124 pass, 1 fail** (`test_ros_log_cleanup.py`). The failure is a real bug,
not a stale test.

The two findings most likely to cost a full day of confused debugging on the bench are
**F1 (odom frame handling)** and **F2 (no LiDAR CRC)**. Both bite the moment the harness
goes on and mapping starts.

---

## Critical — will break mapping

### F1. The odom bridge transforms twist but not pose

`src/scout_odom_bridge.py:88-120`

`_normalize_twist()` swaps `linear.x` / `linear.y` when `forward_axis == "y"` (the
verified setting for this Scout — the checklist confirms `linear.y` = forward). The pose
is passed through untouched, and the `odom -> base_link` TF is built from that untouched
pose.

So either the pose was already in a standard x-forward frame and the twist needed
fixing — which is what the code assumes — or both are in the vendor's y-forward frame and
the pose is now 90 degrees out from the laser frame. In the second case AMCL and gmapping
receive motion that is consistently perpendicular to the scan data, and mapping produces
garbage in a way that looks like bad odometry calibration rather than a frame bug. That
misdiagnosis is the expensive part.

Two smaller problems in the same function:

- The swap `(x, y) = (y, x)` is a **reflection, not a rotation**. It flips handedness,
  so it is inconsistent with the unchanged `angular.z` sign. A 90-degree rotation is
  `x' = -y, y' = x`. Only shows up when `linear.y` is non-zero, so it is dormant while
  `drive_model: diff` and live if anyone sets `omni`.
- It **mutates the received message in place** (`body_twist` aliases `msg.twist.twist`),
  then returns the same object that gets assigned to `odom.twist`. Publisher and
  subscriber share one object.

`src/scout_motion_bridge.py:61-73` has the same reflection-instead-of-rotation issue on
the command path. Also dormant under `diff`.

**Verify before trusting any map:** with the robot on blocks, drive forward 1 m and
confirm `/odom` `pose.position.x` increases by ~1.0 while `y` stays near 0. Then rotate
90 degrees left and confirm yaw increases. See the roadmap for the full procedure.

**Also unverified:** the source topic is `/MotorNode/baselink_odom_relative`. The name
says *relative*. If it publishes per-tick deltas rather than a cumulative pose, the whole
bridge is wrong in a different way. The checklist confirms the topic exists and publishes
at ~10 Hz, but not what its pose semantics are.

### F2. LD19 packets are never CRC-checked

`src/ld19_protocol.py:31-68`

The LD19 frame ends with a CRC8 over the preceding 46 bytes. `parse_ld19_packet()` reads
byte 46 as part of the length check and then ignores it.

The resync path makes this worse. `src/ld19_lidar_driver.py:116-127` recovers from
desync by scanning for the `0x54` header byte — but `0x54` occurs constantly inside
distance and intensity payload, so a false lock is likely, not theoretical. Without a CRC
there is nothing to reject the resulting garbage packet, and it becomes real range data in
a `LaserScan` that feeds the costmap and the safety filter.

A single bad packet can also fake a scan boundary: `LD19ScanAssembler.add_packet()`
declares a revolution complete whenever `start_angle` decreases, so a corrupt angle emits
a truncated scan.

Validating the CRC and requiring `packet[1] == 0x2C` before accepting a header candidate
fixes both. The parser already checks `VER_LEN`, so most of the scaffolding is there.

---

## High — silent data loss and races

### F3. ROS log cleanup deletes far more than it should

`scripts/cleanup_ros_logs.py:15-39` — **this is the failing test.**

`_entry_size()` adds each directory's own inode size (typically 4096 bytes) to the total
as if it were payload. Measured on a tree holding 6144 bytes of logs, it reports 22528 —
a 3.7x over-count that scales with directory count, not log size.

Because the size loop deletes oldest-first until the inflated total drops under the limit,
it can delete every log directory including the newest. That is exactly what
`test_prunes_oldest_entries_until_under_size_limit` catches.

This also makes the documentation wrong.
`docs/LOGGING_ALERTING_RUNBOOK.md:213` promises "100 MiB per configured directory"; the
effective retention is a fraction of that and, in the pathological case, zero. On the
Scout, that means the logs you need to diagnose a field failure are the ones most likely
to have been deleted.

Minor, same file: `cleanup_path()` line 125 reports `min(total, max_bytes)` as usage in
dry-run mode, which is a capped number rather than the real one.

### F4. Shared state mutated from multiple threads without locking

`src/scout_core_runtime.py:100-126`, `src/scout_safety_filter.py`,
`src/scout_battery_dock_guard.py`

The consolidated runtime is one process, but rospy gives each subscriber its own thread
and each `rospy.Timer` another. Nothing is synchronised.

- **Safety filter.** `command_callback()` and the 10 Hz `tick()` both call
  `_publish_decision()`, which mutates `ScoutCommandPublishPolicy` state
  (`stop_sent_for_episode`, `was_command_active`, `last_command_time`). Interleaved, the
  timer can observe a half-updated episode and emit a spurious stop, or consume the
  one-stop-per-episode budget so a genuine stop is suppressed. In a safety filter, a
  suppressed stop is the bad direction.
- **Battery guard.** Four subscribers plus a timer all mutate `self.logic`.
  `_start_vendor_docking()` increments `self.attempt` unguarded, so concurrent entry can
  double-call `/nav_low_bat` or skip a retry.

A single `threading.Lock` around the decision paths in each node resolves both.

### F5. Battery guard can abandon an in-progress dock

`src/scout_battery_dock_guard.py:110-118, 148-169`

`handle_battery()` calls `_reset_to_idle_if_recovered()` on every non-charging battery
message, regardless of current mode. If the reported percent rises above
`min_battery_level + battery_reset_margin` (20 + 5 = 25%) while the guard is in
`vendor_docking` or `map_return`, it drops straight to `idle` and clears
`vendor_deadline`.

This is not a corner case. Battery percent derived from voltage routinely recovers several
points the moment load drops — which is precisely what happens when the robot slows down
to dock. The guard stops tracking a docking run that is still physically underway, the
safety filter unblocks planner commands, and the companion can start commanding motion
while vendor docking is active. Two controllers, one robot.

The recovery check should be gated to `idle` / `return_required` / `failed`, never applied
while a dock is in flight.

### F6. Battery percent is read from unvalidated magic indices

`src/scout_battery_dock_guard.py:385-391`

```python
battery_percent = values[1] if len(values) > 1 else None
charging = bool(values[2]) if len(values) > 2 else False
```

The layout of the vendor `roller_eye/status` array is inferred from rooted inspection and
is nowhere asserted. There is no range check — `_finite_number()` accepts any float. If a
firmware update reorders that array, the guard silently reads the wrong field: a spurious
low value triggers an immediate dock mid-mission, a spurious high value means the robot
never returns and dies flat somewhere in the house.

Clamp to `[0, 100]`, and log loudly and refuse to act on anything outside it.

---

## Medium

### F7. `GlobalPlanner` params are silently ignored

`launch/navigation.launch` loads `config/global_planner_params.yaml`, which is namespaced
under `GlobalPlanner:`, but never sets `move_base`'s `base_global_planner`. move_base
defaults to `navfn/NavfnROS`, so every tuning value in that file — `neutral_cost`,
`cost_factor`, `use_dijkstra`, `allow_unknown` — does nothing.

Either add `<param name="base_global_planner" value="global_planner/GlobalPlanner"/>` or
delete the config file so it stops implying tuning that is not applied.

### F8. Catkin dependencies will break any build on the Scout

`CMakeLists.txt` and `package.xml` declare `move_base`, `amcl`, `gmapping`, `rviz`,
`costmap_2d`, `map_server`, `global_planner`, `dwa_local_planner`, `cv_bridge`, and
`image_transport` as hard dependencies of the single package that gets deployed to
**both** hosts. None of those exist on the Scout's vendor image.

The rsync-based deploy sidesteps this today, but `find_package(catkin REQUIRED
COMPONENTS ...)` will fail hard the first time anyone runs `catkin_make` on the robot —
and nothing in the docs warns against it. Either split companion-only dependencies out or
state the prohibition explicitly.

Also in `CMakeLists.txt`: `catkin_install_python` omits `src/scout_core_runtime.py`, which
is the **default** Scout node (`use_core_runtime` defaults true), along with
`scout_runtime_config.py`, `scout_node_utils.py`, `config_utils.py`, `ld19_protocol.py`,
and `companion_runtime_support.py`. A catkin `install` would produce a runtime that cannot
start. Harmless under rsync deploy, latent otherwise.

### F9. LaserScan `angle_max` is off by one increment

`src/ld19_lidar_driver.py:88-99`

The driver publishes `angle_min = 0`, `angle_max = 2*pi`, `angle_increment = 1 deg`, and
360 ranges. Consumers that compute `n = round((angle_max - angle_min) / angle_increment) + 1`
expect 361. Publish `angle_max = angle_min + (len(ranges) - 1) * angle_increment` instead.

Two related notes:

- `LD19ScanAssembler` bins to a fixed 1-degree grid regardless of the configured
  `angle_min` / `angle_max`. The LD19 produces roughly 450 points per revolution (0.8
  degrees), so about 20% of returns are discarded by dict-key collision on
  `int(angle_degrees)`. Workable, but it is a real resolution loss and is not documented.
- `speed_degrees_per_second` divides the raw field by 100 (`ld19_protocol.py:38`). The
  LD19 reports that field in degrees per second directly, so the value is 100x low. It is
  currently unused, so this is cosmetic — but it is wrong, and anyone who later uses it to
  sanity-check rotor speed will be misled.

### F10. LiDAR parser is bytes/str fragile under Python 2

`ld19_protocol.py:35` compares `packet[0] != LD19_HEADER` (an int) and
`ld19_protocol.py:58` calls `float(packet[offset + 2])`. Under Python 2 — which is what the
Scout runs — both work for `bytearray` and both fail for `bytes`/`str`: the comparison
silently returns `None` for every packet, and the parser appears to work while producing
no scans at all. The driver happens to pass a `bytearray`, so this is latent. Convert
defensively at the parser boundary.

### F11. Tuning values that will not survive first contact

- `urdf/scout.urdf` — `base_to_laser` is `xyz="0.1 0 0.05"`. With `base_link` modelled as
  a 0.15 m long box, x = 0.1 m puts the laser 25 mm **beyond the front edge**, and z = 0.05
  is ~10 mm above the shell. Both are placeholders. This is the harness-gated measurement;
  see `hardware/lidar_harness/`.
- `config/costmap_common_params.yaml` — `inflation_radius: 0.35` around a robot with a
  0.1 m footprint radius. In a house with ~0.76 m doorways, every doorway is saturated
  with inflation cost. Not lethal (inflation is a gradient) but it will produce timid,
  oscillating paths. Expect to drop this to ~0.15–0.20.
- `config/base_local_planner_params.yaml` `max_vel_x: 0.3` contradicts
  `config/scout_config.yaml` `navigation.max_vel_x: 0.25`. Two sources of truth; the
  planner file is the one that takes effect.
- `acc_lim_x: 0.2` with `max_vel_x: 0.3` gives a 0.225 m stopping distance, but
  `emergency_stop_distance` is 0.15 m. At full speed the ToF stop physically cannot stop
  the robot before contact. The caution band (0.3 m, clamped to 0.05 m/s) covers this in
  the normal case, so raise `acc_lim_x` or lower `max_vel_x` rather than treating the ToF
  stop as a backstop.
- The safety filter's caution clamp (`scout_safety_filter.py:229-232`) limits `linear.x`
  only. `angular.z` is unclamped, so the robot can still spin at full rate against a
  close obstacle. Correct for `linear.y` under `diff`; worth revisiting for `omni`.

### F12. No clock synchronisation requirement anywhere

Zero mentions of NTP or chrony across `docs/` and `README.md`.

This is a distributed ROS 1 system: the Scout stamps `/odom`, `/tf`, and `/scan`, and the
Pi runs AMCL and both costmaps against those stamps with `transform_tolerance: 0.5`. If
the two clocks drift more than that — and an embedded board with no RTC can be far worse
after a reboot — TF extrapolation fails and `move_base` refuses to plan, with error
messages that point at TF rather than at the clock.

This belongs in the setup guide as a hard prerequisite, plus a validator check comparing
`date +%s` across both hosts.

---

## Low / hardening

### F13. The Slack webhook is rsynced to the Scout before being replaced

`src/auto_scout/deploy.py:19-25, 528-535`

`SYNC_EXCLUDES` does not include `config/site_local.yaml`, so `deploy_scout()` rsyncs the
full local inventory — including the companion's Slack webhook URL — to the robot, and
only afterwards overwrites it with the role-filtered copy from
`_site_inventory_for_remote_role()`.

The intent of that filtering function is clearly to keep the webhook off the Scout, and it
does for the final state. But the secret still lands on the robot's filesystem with the
local file's permissions, and if the deploy aborts between the rsync and the overwrite it
stays there. Add `config/site_local.yaml` to `SYNC_EXCLUDES`.

### F14. Config values are interpolated into root-run shell without quoting

`src/auto_scout/deploy.py` renders `workspace_dir`, `service_user`, `ros_master_uri`, and
storage paths straight into systemd unit files and into `sudo`-prefixed remote shell
strings (`_install_service_commands`, `_prepare_remote_workspace`). Single quotes are used
in most places, but a value containing an apostrophe breaks out, and the values also land
inside `ExecStart=/bin/bash -lc '...'`.

The source is the operator's own `site_local.yaml`, so this is self-inflicted rather than
an attack surface. Still, these values reach `sudo` — validating them against a
conservative charset at configure time is cheap.

### F15. Battery guard retries by recursion inside a callback

`src/scout_battery_dock_guard.py:371-383`

`_call_vendor_dock()` calls itself on failure via `handle_vendor_call_failed()`. Depth is
bounded by `dock_retry_count` (default 1, so 2 levels), but each level blocks up to 2 s in
`wait_for_service()` inside a subscriber callback. Raising `dock_retry_count` in config
multiplies both. An iterative retry loop, off the callback thread, would be safer.

Related: `MODE_FAILED` is terminal — `_trigger_return()` refuses to re-arm from it, and the
only exit is a battery recovery that cannot happen while not charging. Stopping is the
safe choice, but it means a failed dock bricks autonomy until someone intervenes
physically. That should be stated in the runbook rather than discovered.

### F16. The one-stop-per-episode policy has no redundancy

`src/scout_safety_filter.py:281-313`

The single-stop design is deliberate and well-reasoned — the checklist records that
periodic zeros broke iOS manual driving and vendor docking on 2026-04-28. But exactly one
stop message covers a moving robot. ROS 1 TCP delivery makes loss unlikely within a
process, and the filter runs on the Scout so a network partition does not disable it.
Still, a short burst (3 stops over ~0.3 s) on the blocking transition would cost nothing
in the manual-drive case, since no planner episode is active then.

---

## Documentation accuracy

The prose docs are unusually good — `VERIFIED_ARCHITECTURE.md` separates verified fact
from inference, and `AUTO_SCOUT_CHECKLIST.md` carries dated live-validation results that
made this review much faster. Three concrete inaccuracies:

1. **`README.md` directory listing is stale.** It claims to cover "the maintained tracked
   project tree" but omits 17 tracked files: `docs/ROCKCHIP_SERVICE_FINDINGS.md`,
   `scripts/provision_pi_known_hosts.sh`, four systemd units (resource-metrics and
   resource-alert service/timer pairs), three source modules (`companion_notifications.py`,
   `auto_scout/notifications.py`, `auto_scout/network_validation.py`, `auto_scout/redaction.py`),
   and seven test files. A generated listing would stop this recurring.
2. **`LOGGING_ALERTING_RUNBOOK.md:213`** documents 100 MiB ROS log retention that F3 shows
   is not what actually happens.
3. **Launch defaults point at the sample inventory.** Both `scout_runtime.launch` and
   `companion_runtime.launch` default `site_file` to `config/site.yaml` — the tracked
   sample with `.invalid` placeholders — not `config/site_local.yaml`. The start scripts
   override it correctly, so the deployed path is fine, but anyone running `roslaunch`
   by hand for debugging silently gets the sample inventory.

Minor: `config/scout_config.yaml` still carries a `web: port: 8080` block for the retired
web interface.

---

## What is genuinely good

Worth recording so it does not get "cleaned up" later:

- **Safety authority lives on the robot.** The battery guard and safety filter run on the
  Scout, so a companion crash or Wi-Fi drop cannot disable them. This is the correct
  split and many hobby projects get it backwards.
- **Vendor docking is not reimplemented.** Handing the final physical dock back to
  `/nav_low_bat` and monitoring `/CoreNode/going_home_status`, rather than hand-rolling a
  visual servo, is the right scope decision.
- **`/CoreNode/backing_up` is documented as do-not-subscribe** because vendor code treats
  subscription as a trigger. That is exactly the kind of hard-won detail that gets lost.
- **The pure-logic / ROS-wrapper split** (`ScoutSafetyLogic`, `ScoutBatteryDockGuardLogic`)
  makes the safety-critical decisions unit-testable without ROS, and the tests exercise
  them properly. This is why F4 and F5 are the only logic-level findings in those files.
- **Secret handling** is deliberate: gitignored local inventory, a redaction module for
  artifacts, and role-filtered inventory on deploy.
- **`.invalid` placeholders** in the tracked sample, so a fresh checkout cannot
  accidentally deploy against someone else's network.

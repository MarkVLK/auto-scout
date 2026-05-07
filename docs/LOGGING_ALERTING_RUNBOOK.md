# Logging And Alerting Runbook

This runbook is the starting point for any troubleshooting session. Use it to
decide where to look first, which warnings are expected, where alerts should be
sent, and how long each log source is expected to survive.

The current deployed reference system is:

- Scout: `linaro@192.168.0.199` / `moorebot-scout.local`
- Pi companion: `automark@auto-scout-pi5.local`
- Scout Auto-Scout workspace: `/userdata/catkin_ws/src/auto-scout`
- Pi Auto-Scout workspace: `/home/automark/auto-scout`

Do not paste raw logs publicly without reviewing them. Vendor WiFi logs can
include SSIDs and credentials, and local site inventory can contain the Slack
incoming-webhook URL.

## First Commands

Use these commands first when an event happens. Replace the `--since` window
with the suspected incident window.

```bash
ssh -o LogLevel=ERROR linaro@192.168.0.199 "date; uptime"
ssh -o LogLevel=ERROR linaro@192.168.0.199 "systemctl is-active auto-scout-scout-runtime.service auto-scout-scout-resource-metrics.timer"
ssh -o LogLevel=ERROR linaro@192.168.0.199 "cat /proc/swaps; free -m; vmstat 1 5"
ssh -o LogLevel=ERROR linaro@192.168.0.199 "sudo -n journalctl --since '15 minutes ago' --no-pager"
ssh -o LogLevel=ERROR linaro@192.168.0.199 "sudo -n journalctl -k --since '15 minutes ago' --no-pager"
```

For Pi-side issues:

```bash
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local "date; uptime"
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local "systemctl is-active auto-scout-companion-runtime.service auto-scout-companion-resource-alert.timer"
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local "docker ps; docker stats --no-stream auto-scout-melodic"
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local "journalctl --since '15 minutes ago' --no-pager -u auto-scout-companion-runtime.service -u auto-scout-companion-resource-alert.service"
```

For alert-path checks:

```bash
./auto-scout --site config/site_local.yaml notify test
./auto-scout --site config/site_local.yaml notify resource-check --force-alert
./auto-scout --site config/site_local.yaml validate scout --skip-connectivity-check --quiet
```

## Source Inventory

| Source | Host | Path or command | Contains | Retention or limit | Configuration |
| --- | --- | --- | --- | --- | --- |
| systemd journal | Scout | `journalctl`, `journalctl -k` | Vendor stack, kernel, Auto-Scout service stdout/stderr, WiFi/audio events, OOM lines | Persistent journal is limited to `SystemMaxUse=32M`, runtime journal to `RuntimeMaxUse=32M`, and `MaxRetentionSec=7day` on the live Scout | Live `/etc/systemd/journald.conf`; tracked status in [docs/AUTO_SCOUT_CHECKLIST.md](AUTO_SCOUT_CHECKLIST.md) |
| file syslog | Scout | `/var/log/*` | Forwarded syslog/journal text when available | Vendor `cleanLog.sh` truncates immediate files over 100 KiB, so do not rely on long retention | Live `/usr/local/bin/cleanLog.sh`; journald forwarding in `/etc/systemd/journald.conf` |
| vendor runtime log stream | Scout | `journalctl --since ... \| grep roller_eye-start` | Moorebot vendor nodes, WiFi state, cloud login, speaker playback, camera/vendor events | Governed by journald limits above; file copies can be truncated by vendor cleanup | Vendor `/usr/sbin/roller_eye-start` and `/tmp/roller_eye.launch` |
| vendor ROS logs | Scout | `/tmp/<ros-run-id>/*` and `/tmp/<ros-run-id>/*-stdout.log` | Per-node vendor ROS logs such as `WiFiNode`, `CoreNode`, `SpeakerNode`, `SensorNode`, `MotorNode` | Not guaranteed long term; `/tmp` is volatile and vendor cleanup may affect nearby vendor temp paths | Vendor ROS launch/runtime |
| Auto-Scout Scout runtime journal | Scout | `journalctl -u auto-scout-scout-runtime.service` | `scout_core_runtime.py`, optional LD19/camera process launch, runtime crashes/restarts | Governed by Scout journald limits | Rendered by [src/auto_scout/deploy.py](../src/auto_scout/deploy.py); example [systemd/auto-scout-scout-runtime.service](../systemd/auto-scout-scout-runtime.service) |
| Auto-Scout Scout ROS logs | Scout | `/userdata/auto-scout/ros-logs` | ROS logs for deploy-managed Scout runtime | Daily cleanup after boot; max age 7 days and max total 100 MiB per configured directory | [scripts/cleanup_ros_logs.py](../scripts/cleanup_ros_logs.py), [src/auto_scout/deploy.py](../src/auto_scout/deploy.py), [systemd/auto-scout-ros-log-cleanup.service](../systemd/auto-scout-ros-log-cleanup.service) |
| legacy Scout ROS logs | Scout | `/home/linaro/.ros/log` | Older/default ROS logs if any process ignores `ROS_LOG_DIR` | Same Auto-Scout daily cleanup policy: 7 days, 100 MiB | Installed by Scout deploy as an extra cleanup path |
| Scout resource snapshots | Scout | `/userdata/auto-scout/resource-metrics/snapshot-*.txt` | Uptime/load, memory, swap, `vmstat`, disk, top RSS/CPU, Auto-Scout process list | Every 15 minutes; snapshots older than 14 days are deleted | [scripts/collect_scout_resource_metrics.sh](../scripts/collect_scout_resource_metrics.sh), [systemd/auto-scout-scout-resource-metrics.timer](../systemd/auto-scout-scout-resource-metrics.timer) |
| Pi companion runtime journal | Pi | `journalctl -u auto-scout-companion-runtime.service` | Companion Docker stack start/stop and service failures | Host journald policy on the Pi | Rendered by [src/auto_scout/deploy.py](../src/auto_scout/deploy.py); example [systemd/auto-scout-companion-runtime.service](../systemd/auto-scout-companion-runtime.service) |
| companion container logs | Pi | `docker logs auto-scout-melodic` | ROS launch stdout/stderr inside the companion container | Docker default unless host Docker config changes | [container/docker-compose.yml](../container/docker-compose.yml) |
| Auto-Scout Pi ROS logs | Pi | `/srv/auto-scout/ros-logs` | ROS logs from the companion runtime/container | Daily cleanup after boot; max age 7 days and max total 100 MiB per configured directory | [scripts/cleanup_ros_logs.py](../scripts/cleanup_ros_logs.py), [scripts/start_companion_stack.sh](../scripts/start_companion_stack.sh), [src/auto_scout/deploy.py](../src/auto_scout/deploy.py) |
| Pi resource-alert timer journal | Pi | `journalctl -u auto-scout-companion-resource-alert.service` | Critical resource-check JSON, Slack delivery status, cooldown/recovery decisions | Host journald policy on the Pi | [systemd/auto-scout-companion-resource-alert.service](../systemd/auto-scout-companion-resource-alert.service), [systemd/auto-scout-companion-resource-alert.timer](../systemd/auto-scout-companion-resource-alert.timer) |
| Pi resource-alert state | Pi | `/srv/auto-scout/alert-state/resource-alert-state.json` | Active alert fingerprint, last sent timestamp, last status | Current state file only; same active alert repeats at most every 6 hours | [src/auto_scout/resource_alerts.py](../src/auto_scout/resource_alerts.py) |
| CLI run artifacts | Machine running CLI | `artifacts/runs/<timestamp>-<command>/` | `run.log`, redacted JSON reports for configure/deploy/validate/notify/mission commands | No automatic cleanup in repo; ignored by git | [src/auto_scout/artifacts.py](../src/auto_scout/artifacts.py), [src/auto_scout/cli.py](../src/auto_scout/cli.py) |
| mission controller logs | Companion/container and artifacts | ROS logs plus `mission.log` under each mission artifact directory | Mission phase progress, proof-photo path, Slack send status, preflight refusal reason | ROS/artifact retention as above | [src/auto_scout/runtime/mission_controller.py](../src/auto_scout/runtime/mission_controller.py) |

## Warning And Alert Routing

Slack notifications are sent only by the Pi companion. The Scout should not
store webhook secrets or send Slack directly.

The webhook lives in ignored local inventory:

```yaml
roles:
  companion:
    capabilities:
      notify: true
    notifications:
      webhook_url: "https://hooks.slack.com/services/..."
```

Normal Slack notification types:

- `./auto-scout notify test`: manual webhook delivery test.
- Mission success: sent by the companion mission controller when the mission
  requires notification and the webhook is configured.
- Mission preflight refusal: sent before motion when a required condition is
  missing, such as disabled nav stack or insufficient battery.
- Critical resource alerts: sent by
  `auto-scout-companion-resource-alert.timer` every 15 minutes when a critical
  condition is active, with same-fingerprint repeats suppressed for 6 hours.
- Resource recovery: sent once when the active resource-alert fingerprint clears.

Critical resource alerts currently include:

- Scout OOM/SIGKILL lines in recent kernel/service logs.
- Scout runtime service down.
- Scout swap unit missing or `/userdata/auto-scout/auto-scout.swap` absent from
  `/proc/swaps`.
- Scout resource metrics timer down.
- Scout available memory below 150 MiB.
- Scout root filesystem free space below 250 MiB.
- Scout interval swap I/O at or above 256 KiB/s. The first `vmstat` row is
  ignored because it is a since-boot average.
- Scout Auto-Scout process CPU at or above 60 percent.
- Scout Auto-Scout process RSS at or above 80 MiB.
- Pi failed systemd units.
- Pi available memory below 1 GiB.
- Pi root filesystem free space below 5 GiB.
- Pi companion container down.
- Pi OOM/SIGKILL lines in recent kernel logs.

Expected no-LD19/no-nav holding-mode skips must not page Slack. In the current
holding mode, missing `/scan`, disabled mapping, disabled patrol, and disabled
smoke-loop autonomy are expected until `AUTO_SCOUT_ENABLE_LIDAR=true` and
`AUTO_SCOUT_ENABLE_NAV_STACK=true` are deliberately restored.

When the resource-alert command runs locally on the Pi, it targets the Scout via
`roles.scout.ssh.host_key_alias` when present. Keep the Pi-local
`~/.ssh/config` and known-host entry valid for `moorebot-scout.local`; otherwise
the timer can fail to collect Scout health even when manual Mac-to-Scout SSH
works.

## Common Incidents

### Scout Plays A Sound

Search for vendor audio and WiFi events:

```bash
ssh -o LogLevel=ERROR linaro@192.168.0.199 \
  "sudo -n journalctl --since '15 minutes ago' --no-pager | grep -Ei 'Playing WAVE|WIFI_EVENT|Link Down|Lost carrier|CTRL-EVENT|wifiLED|cloud|login'"
```

Known examples:

- `/var/roller_eye/devAudio/connect/connect_wifi.wav`: vendor WiFi reconnect started.
- `/var/roller_eye/devAudio/connect/success.wav`: vendor WiFi reconnected and got IP.

These are vendor events, not Auto-Scout sounds, unless an Auto-Scout mission log
also shows an explicit notification or media action at the same time.

### Many Root Session Open/Close Lines

This is expected on the vendor image when the lines include:

```text
COMMAND=/usr/local/bin/cleanLog.sh
```

The vendor stack repeatedly runs `sudo /usr/local/bin/cleanLog.sh`, which opens
and closes a PAM session for root each time. This is not a root login. The script
truncates immediate files under `/var/log` and `/tmp/latest` over 100 KiB. It is
noisy but currently harmless to Auto-Scout logs because Auto-Scout uses
`/userdata/auto-scout/...`.

### Suspected OOM Or Process Kill

Check both kernel logs and resource snapshots:

```bash
ssh -o LogLevel=ERROR linaro@192.168.0.199 \
  "sudo -n journalctl -k --since '24 hours ago' --no-pager | grep -Ei 'Out of memory|oom-killer|Killed process|exit code -9'"
ssh -o LogLevel=ERROR linaro@192.168.0.199 \
  "latest=\$(ls -t /userdata/auto-scout/resource-metrics | head -1); ls -lt /userdata/auto-scout/resource-metrics | head; tail -120 /userdata/auto-scout/resource-metrics/\${latest}"
```

Then run the companion alert check:

```bash
./auto-scout --site config/site_local.yaml notify resource-check --force-alert
```

### Missing Camera Frames

The normal still-photo path is the lazy Pi bridge from vendor `/CoreNode/jpg` to
`/camera/image_raw/compressed`. Check that it subscribes only while consumers are
present:

```bash
ssh -o LogLevel=ERROR linaro@192.168.0.199 \
  "env PYTHONPATH=/opt/ros/melodic/lib/python2.7/dist-packages ROS_MASTER_URI=http://localhost:11311 /opt/ros/melodic/bin/rostopic info /CoreNode/jpg"
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local \
  "journalctl --since '15 minutes ago' --no-pager | grep -Ei 'vendor_jpg_bridge|camera|jpg|photo'"
```

When idle, `/CoreNode/jpg` should have no `vendor_jpg_bridge` subscriber.

### Scout Resource Alert Timer Reports Scout SSH Failure

From the Pi, verify the alias path:

```bash
ssh -o LogLevel=ERROR automark@auto-scout-pi5.local \
  "ssh -o BatchMode=yes -o ConnectTimeout=5 linaro@moorebot-scout.local systemctl is-active auto-scout-scout-runtime.service"
```

If this fails but Mac-to-Scout SSH works, fix the Pi's `~/.ssh/config`,
known-host entry, or validation key selection for `moorebot-scout.local`.

## Retention Configuration Reference

| Setting | Default | Where configured |
| --- | --- | --- |
| Scout persistent journal size | `SystemMaxUse=32M` | Live `/etc/systemd/journald.conf`; tracked in checklist |
| Scout runtime journal size | `RuntimeMaxUse=32M` | Live `/etc/systemd/journald.conf`; tracked in checklist |
| Scout journal age | `MaxRetentionSec=7day` | Live `/etc/systemd/journald.conf`; tracked in checklist |
| journald to syslog forwarding | `ForwardToSyslog=yes` | Live `/etc/systemd/journald.conf`; tracked in checklist |
| vendor file truncation | files over 100 KiB in `/var/log` and `/tmp/latest` | Live `/usr/local/bin/cleanLog.sh` |
| Auto-Scout ROS log max age | 7 days | `ROS_LOG_MAX_AGE_DAYS` in [src/auto_scout/deploy.py](../src/auto_scout/deploy.py); rendered to systemd env |
| Auto-Scout ROS log max bytes | 100 MiB per configured directory | `ROS_LOG_MAX_BYTES` in [src/auto_scout/deploy.py](../src/auto_scout/deploy.py); [scripts/cleanup_ros_logs.py](../scripts/cleanup_ros_logs.py) |
| ROS cleanup timer cadence | 5 minutes after boot, then every 1 day | [src/auto_scout/deploy.py](../src/auto_scout/deploy.py), [systemd/auto-scout-ros-log-cleanup.timer](../systemd/auto-scout-ros-log-cleanup.timer) |
| Scout resource snapshot cadence | 10 minutes after boot, then every 15 minutes | [systemd/auto-scout-scout-resource-metrics.timer](../systemd/auto-scout-scout-resource-metrics.timer) |
| Scout resource snapshot max age | 14 days | `AUTO_SCOUT_RESOURCE_METRICS_MAX_AGE_DAYS` in [scripts/collect_scout_resource_metrics.sh](../scripts/collect_scout_resource_metrics.sh) |
| resource alert cadence | 15 minutes after boot, then every 15 minutes | [systemd/auto-scout-companion-resource-alert.timer](../systemd/auto-scout-companion-resource-alert.timer) |
| repeated active alert cooldown | 6 hours | `DEFAULT_ALERT_COOLDOWN_SECONDS` in [src/auto_scout/resource_alerts.py](../src/auto_scout/resource_alerts.py) |
| resource alert state path | `/srv/auto-scout/alert-state/resource-alert-state.json` | [src/auto_scout/deploy.py](../src/auto_scout/deploy.py), companion resource-alert service |
| Slack webhook URL | ignored local config only | `config/site_local.yaml`, `roles.companion.notifications.webhook_url` |
| CLI artifact retention | no automatic cleanup | [src/auto_scout/artifacts.py](../src/auto_scout/artifacts.py); `artifacts/` is gitignored |

## Interpretation Rules For Future LLM Sessions

- Start with exact device time, uptime, service state, and the event window.
- Prefer `journalctl` for vendor incidents because vendor file logs are
  aggressively truncated.
- Prefer `/userdata/auto-scout/resource-metrics` for Scout resource history
  because the base image does not provide reliable long-term `sar` history.
- Treat Slack webhook URLs, WiFi credentials, and local inventory as secrets.
- Do not interpret expected no-LD19/no-nav skips as failures while the LD19 is
  detached.
- Do not disable vendor `cleanLog.sh` without a separate risk review; it helps
  keep the small Scout root filesystem from filling.
- Do not rely on `/var/log` for complete history on the Scout; use journald,
  Auto-Scout ROS logs, resource snapshots, and Pi-side artifacts together.

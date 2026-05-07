"""Critical resource alert collection and cooldown logic."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import socket
import time
from pathlib import Path
from typing import Optional

from auto_scout.command_runner import CommandRunner
from auto_scout.site_config import companion_storage_root
from auto_scout.site_config import role_config


SCOUT_MIN_AVAILABLE_MEMORY_MIB = 150
SCOUT_MIN_ROOT_FREE_MIB = 250
SCOUT_AUTO_NODE_CPU_WARN_PERCENT = 60.0
SCOUT_AUTO_NODE_RSS_WARN_MIB = 80.0
SCOUT_SWAP_IO_CRITICAL_KIB_PER_SECOND = 256
PI_MIN_AVAILABLE_MEMORY_MIB = 1024
PI_MIN_ROOT_FREE_MIB = 5 * 1024
DEFAULT_ALERT_COOLDOWN_SECONDS = 6 * 60 * 60
DEFAULT_STATE_FILENAME = "resource-alert-state.json"

SCOUT_RUNTIME_SERVICE = "auto-scout-scout-runtime.service"
SCOUT_RESOURCE_METRICS_TIMER = "auto-scout-scout-resource-metrics.timer"
SCOUT_SWAP_UNIT = "userdata-auto\\x2dscout-auto\\x2dscout.swap.swap"
COMPANION_CONTAINER_NAME = "auto-scout-melodic"


@dataclass
class AlertDelivery:
    should_send: bool
    reason: str
    payload: Optional[dict]
    fingerprint: str
    state_path: Optional[str]


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_alert_state_dir(site_config):
    companion = role_config(site_config, "companion")
    return "{}/alert-state".format(companion_storage_root(companion))


def default_local_companion(site_config):
    companion = role_config(site_config, "companion")
    candidates = {
        str(companion.get("hostname") or "").split(".")[0],
        str(companion.get("ssh", {}).get("host") or "").split(".")[0],
    }
    local_names = {socket.gethostname().split(".")[0], socket.getfqdn().split(".")[0]}
    return bool((candidates - {""}) & (local_names - {""}))


def scout_ssh_config_for_resource_check(scout_ssh, local_companion=False):
    ssh_config = dict(scout_ssh or {})
    host_key_alias = str(ssh_config.get("host_key_alias") or "").strip()
    if local_companion and host_key_alias:
        ssh_config["host"] = host_key_alias
    return ssh_config


def _sectioned_output(sections):
    lines = []
    for name, body in sections:
        lines.append("__{}__".format(name))
        lines.append(body)
    return "\n".join(lines)


def _split_sections(output):
    sections = {}
    current = None
    lines = []
    for line in (output or "").splitlines():
        if line.startswith("__") and line.endswith("__"):
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = line.strip("_")
            lines = []
            continue
        if current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def _parse_free_available_mib(free_output):
    for line in (free_output or "").splitlines():
        parts = line.split()
        if parts and parts[0].startswith("Mem:") and len(parts) >= 7:
            try:
                return int(parts[6])
            except ValueError:
                return None
    return None


def _parse_vmstat_swap_io(vmstat_output):
    max_si = 0
    max_so = 0
    data_rows = 0
    for line in (vmstat_output or "").splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].lstrip("-").isdigit():
            continue
        data_rows += 1
        if data_rows == 1:
            continue
        try:
            max_si = max(max_si, int(parts[6]))
            max_so = max(max_so, int(parts[7]))
        except ValueError:
            continue
    return max_si, max_so


def _parse_df_free_mib(df_output, mount_point="/"):
    for line in (df_output or "").splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[-1] != mount_point:
            continue
        try:
            return int(parts[3]) // 1024
        except ValueError:
            return None
    return None


def _parse_units(unit_output):
    units = {}
    for line in (unit_output or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            units[parts[0]] = parts[1].strip()
    return units


def _parse_auto_scout_process_alerts(ps_output):
    alerts = []
    for line in (ps_output or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or parts[0] == "PID":
            continue
        pid, command, cpu_text, rss_text, args = parts
        if "/auto-scout/" not in args and "auto-scout" not in args:
            continue
        try:
            cpu = float(cpu_text)
            rss_mib = int(rss_text) / 1024.0
        except ValueError:
            continue
        if cpu >= SCOUT_AUTO_NODE_CPU_WARN_PERCENT:
            alerts.append(
                _alert(
                    "scout_process_cpu_{}".format(pid),
                    "Scout Auto-Scout process CPU is high",
                    "{} ({}) is using {:.1f}% CPU".format(pid, command, cpu),
                )
            )
        if rss_mib >= SCOUT_AUTO_NODE_RSS_WARN_MIB:
            alerts.append(
                _alert(
                    "scout_process_rss_{}".format(pid),
                    "Scout Auto-Scout process RSS is high",
                    "{} ({}) is using {:.1f} MiB RSS".format(pid, command, rss_mib),
                )
            )
    return alerts


def _oom_lines(output):
    return [
        line.strip()
        for line in (output or "").splitlines()
        if any(
            marker in line
            for marker in ["Out of memory", "oom-killer", "Killed process", "exit code -9"]
        )
    ]


def _alert(alert_id, summary, detail):
    return {"id": alert_id, "severity": "critical", "summary": summary, "detail": detail}


def scout_health_command():
    return (
        "printf '__UNITS__\\n'; "
        "for u in {runtime} {metrics} '{swap}'; do printf '%s ' \"$u\"; systemctl is-active \"$u\" 2>/dev/null || true; done; "
        "printf '__FREE__\\n'; free -m || true; "
        "printf '__SWAPS__\\n'; cat /proc/swaps || true; "
        "printf '__VMSTAT__\\n'; vmstat 1 3 || true; "
        "printf '__DF__\\n'; df -Pk / /userdata /tmp 2>/dev/null || df -Pk || true; "
        "printf '__PS__\\n'; ps -eo pid,comm,%cpu,rss,args --sort=-%cpu | head -40 || true; "
        "printf '__OOM__\\n'; "
        "{{ sudo -n journalctl -k --since '24 hours ago' --no-pager 2>/dev/null "
        "|| journalctl -k --since '24 hours ago' --no-pager 2>/dev/null "
        "|| dmesg 2>/dev/null || true; "
        "sudo -n journalctl --since '24 hours ago' --no-pager -u {runtime} -u {metrics} -u '{swap}' 2>/dev/null || true; }} "
        "| grep -E 'Out of memory|oom-killer|Killed process|exit code -9' || true"
    ).format(
        runtime=SCOUT_RUNTIME_SERVICE,
        metrics=SCOUT_RESOURCE_METRICS_TIMER,
        swap=SCOUT_SWAP_UNIT,
    )


def companion_health_command(container_name=COMPANION_CONTAINER_NAME):
    return (
        "printf '__FAILED_UNITS__\\n'; systemctl --failed --no-legend --plain 2>/dev/null || true; "
        "printf '__FREE__\\n'; free -m || true; "
        "printf '__DF__\\n'; df -Pk / /srv/auto-scout 2>/dev/null || df -Pk / || true; "
        "printf '__DOCKER__\\n'; docker inspect -f '{{{{.State.Running}}}} {{{{.Name}}}}' {container} 2>/dev/null || true; "
        "printf '__DOCKER_STATS__\\n'; docker stats --no-stream --format '{{{{.Name}}}}\\t{{{{.CPUPerc}}}}\\t{{{{.MemUsage}}}}\\t{{{{.MemPerc}}}}' {container} 2>/dev/null || true; "
        "printf '__OOM__\\n'; journalctl -k --since '24 hours ago' --no-pager 2>/dev/null "
        "| grep -E 'Out of memory|oom-killer|Killed process|exit code -9' || true"
    ).format(container=container_name)


def collect_resource_health(site_config, runner=None, local_companion=None):
    runner = runner or CommandRunner()
    scout = role_config(site_config, "scout")
    companion = role_config(site_config, "companion")
    if local_companion is None:
        local_companion = default_local_companion(site_config)

    scout_ssh = scout_ssh_config_for_resource_check(
        scout.get("ssh", {}),
        local_companion=local_companion,
    )
    scout_result = runner.run_remote(scout_ssh, scout_health_command(), check=False, connect_timeout=8)
    if local_companion:
        companion_result = runner.run(companion_health_command(), check=False)
    else:
        companion_result = runner.run_remote(
            companion.get("ssh", {}),
            companion_health_command(companion.get("ros", {}).get("container_name", COMPANION_CONTAINER_NAME)),
            check=False,
            connect_timeout=8,
        )
    return {
        "scout": parse_scout_health(scout_result.stdout, command_ok=scout_result.ok),
        "companion": parse_companion_health(companion_result.stdout, command_ok=companion_result.ok),
        "local_companion": bool(local_companion),
    }


def parse_scout_health(output, command_ok=True):
    sections = _split_sections(output)
    alerts = []
    units = _parse_units(sections.get("UNITS", ""))
    for unit in [SCOUT_RUNTIME_SERVICE, SCOUT_RESOURCE_METRICS_TIMER, SCOUT_SWAP_UNIT]:
        if units.get(unit) != "active":
            alerts.append(_alert("scout_unit_{}".format(unit), "Scout required unit is not active", "{} is {}".format(unit, units.get(unit, "unknown"))))

    swaps = sections.get("SWAPS", "")
    if "/userdata/auto-scout/auto-scout.swap" not in swaps:
        alerts.append(_alert("scout_swap_missing", "Scout swap is missing", "/userdata/auto-scout/auto-scout.swap is not active in /proc/swaps"))

    available_mib = _parse_free_available_mib(sections.get("FREE", ""))
    if available_mib is not None and available_mib < SCOUT_MIN_AVAILABLE_MEMORY_MIB:
        alerts.append(_alert("scout_low_memory", "Scout available memory is low", "{} MiB available".format(available_mib)))

    max_si, max_so = _parse_vmstat_swap_io(sections.get("VMSTAT", ""))
    if max_si >= SCOUT_SWAP_IO_CRITICAL_KIB_PER_SECOND or max_so >= SCOUT_SWAP_IO_CRITICAL_KIB_PER_SECOND:
        alerts.append(
            _alert(
                "scout_swap_io",
                "Scout swap I/O is active",
                "max si={} KiB/s, max so={} KiB/s over threshold {} KiB/s".format(
                    max_si,
                    max_so,
                    SCOUT_SWAP_IO_CRITICAL_KIB_PER_SECOND,
                ),
            )
        )

    root_free_mib = _parse_df_free_mib(sections.get("DF", ""), "/")
    if root_free_mib is not None and root_free_mib < SCOUT_MIN_ROOT_FREE_MIB:
        alerts.append(_alert("scout_root_disk_low", "Scout root filesystem is low", "{} MiB free".format(root_free_mib)))

    oom = _oom_lines(sections.get("OOM", ""))
    if oom:
        alerts.append(_alert("scout_oom", "Scout OOM/SIGKILL lines found", "; ".join(oom[:3])))

    alerts.extend(_parse_auto_scout_process_alerts(sections.get("PS", "")))
    if not command_ok:
        alerts.append(_alert("scout_health_command_failed", "Scout resource check command failed", "Scout SSH/resource collection returned nonzero"))

    return {
        "ok": not alerts,
        "alerts": alerts,
        "evidence": {
            "available_memory_mib": available_mib,
            "root_free_mib": root_free_mib,
            "max_swap_in_kib_per_second": max_si,
            "max_swap_out_kib_per_second": max_so,
            "units": units,
            "swap_active": "/userdata/auto-scout/auto-scout.swap" in swaps,
        },
    }


def parse_companion_health(output, command_ok=True):
    sections = _split_sections(output)
    alerts = []
    failed_units = [line.strip() for line in sections.get("FAILED_UNITS", "").splitlines() if line.strip()]
    if failed_units:
        alerts.append(_alert("pi_failed_units", "Pi has failed systemd units", "; ".join(failed_units[:3])))

    available_mib = _parse_free_available_mib(sections.get("FREE", ""))
    if available_mib is not None and available_mib < PI_MIN_AVAILABLE_MEMORY_MIB:
        alerts.append(_alert("pi_low_memory", "Pi available memory is low", "{} MiB available".format(available_mib)))

    root_free_mib = _parse_df_free_mib(sections.get("DF", ""), "/")
    if root_free_mib is not None and root_free_mib < PI_MIN_ROOT_FREE_MIB:
        alerts.append(_alert("pi_root_disk_low", "Pi root filesystem is low", "{} MiB free".format(root_free_mib)))

    docker = sections.get("DOCKER", "")
    container_running = docker.startswith("true ")
    if not container_running:
        alerts.append(_alert("pi_container_down", "Companion container is not running", docker or "docker inspect produced no running container"))

    oom = _oom_lines(sections.get("OOM", ""))
    if oom:
        alerts.append(_alert("pi_oom", "Pi OOM/SIGKILL lines found", "; ".join(oom[:3])))

    if not command_ok:
        alerts.append(_alert("pi_health_command_failed", "Pi resource check command failed", "Pi resource collection returned nonzero"))

    return {
        "ok": not alerts,
        "alerts": alerts,
        "evidence": {
            "available_memory_mib": available_mib,
            "root_free_mib": root_free_mib,
            "container_running": container_running,
            "docker_stats": sections.get("DOCKER_STATS", ""),
            "failed_units": failed_units,
        },
    }


def summarize_resource_health(health, timestamp=None):
    alerts = []
    for role in ["scout", "companion"]:
        alerts.extend(health.get(role, {}).get("alerts", []))
    return {
        "ok": not alerts,
        "status": "critical" if alerts else "ok",
        "timestamp": timestamp or utc_timestamp(),
        "alerts": alerts,
        "health": health,
    }


def fingerprint_alerts(alerts):
    ids = sorted(alert.get("id", "") for alert in alerts)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest() if ids else ""


def _state_path(state_dir):
    if not state_dir:
        return None
    return Path(state_dir) / DEFAULT_STATE_FILENAME


def load_alert_state(state_dir):
    path = _state_path(state_dir)
    if not path or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_alert_state(state_dir, state):
    path = _state_path(state_dir)
    if not path:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def choose_alert_delivery(report, state_dir=None, force_alert=False, cooldown_seconds=DEFAULT_ALERT_COOLDOWN_SECONDS):
    alerts = report.get("alerts", [])
    fingerprint = fingerprint_alerts(alerts)
    state = load_alert_state(state_dir)
    now = time.time()
    previous = state.get("active_fingerprint", "")
    last_sent = float(state.get("last_sent", 0.0) or 0.0)

    should_send = False
    reason = "no_alert"
    status = report.get("status", "ok")
    if force_alert:
        should_send = True
        reason = "forced"
    elif alerts:
        should_send = fingerprint != previous or now - last_sent >= float(cooldown_seconds)
        reason = "new_alert" if fingerprint != previous else ("cooldown_elapsed" if should_send else "cooldown_suppressed")
    elif previous:
        should_send = True
        reason = "recovered"

    state_path = None
    if should_send or alerts or previous:
        state_path = save_alert_state(
            state_dir,
            {
                "active_fingerprint": fingerprint,
                "last_sent": now if should_send else last_sent,
                "last_status": status,
                "updated_at": utc_timestamp(),
            },
        )

    return AlertDelivery(
        should_send=should_send,
        reason=reason,
        payload=None,
        fingerprint=fingerprint,
        state_path=state_path,
    )

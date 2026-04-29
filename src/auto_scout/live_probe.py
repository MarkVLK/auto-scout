"""Live Scout capability probing and site-inventory reconciliation."""

import csv
import io
import math
import os
import re
import shlex
import time
from copy import deepcopy
from pathlib import Path

from auto_scout.command_runner import CommandRunner
from auto_scout.site_config import (
    role_config,
    role_device,
    role_motion_setting,
    role_ros_setting,
    role_topic,
)


MOTION_DELTA_THRESHOLD = 0.05
DEFAULT_OBSERVE_MOTION_SECONDS = 0.0

TOPIC_CANDIDATES = {
    "lidar_scan": ["/scan"],
    "camera_compressed": ["/camera/image_raw/compressed"],
    "scout_tof": ["/SensorNode/tof"],
    "tof_range": ["/scout/tof"],
    "scout_imu": ["/SensorNode/imu"],
    "imu_data": ["/scout/imu/data"],
    "odom": ["/MotorNode/baselink_odom_relative", "/MotorNode/vio_odom_relative", "/odom"],
    "vendor_cmd_vel": ["/cmd_vel_force", "/cmd_vel"],
    "planner_cmd_vel": ["/scout/cmd_vel_planner"],
    "autonomy_cmd_vel": ["/scout/cmd_vel_companion"],
    "safety_state": ["/scout/safety_state"],
    "battery_status": ["/SensorNode/simple_battery_status"],
    "battery_guard_state": ["/scout/battery_guard_state"],
    "vendor_dock_status": ["/CoreNode/going_home_status"],
}

TOPIC_TYPES = {
    "lidar_scan": "sensor_msgs/LaserScan",
    "camera_compressed": "sensor_msgs/CompressedImage",
    "scout_tof": "sensor_msgs/Range",
    "tof_range": "sensor_msgs/Range",
    "scout_imu": "sensor_msgs/Imu",
    "imu_data": "sensor_msgs/Imu",
    "odom": "nav_msgs/Odometry",
    "vendor_cmd_vel": "geometry_msgs/Twist",
    "planner_cmd_vel": "geometry_msgs/Twist",
    "autonomy_cmd_vel": "geometry_msgs/Twist",
    "safety_state": "std_msgs/String",
    "battery_status": "roller_eye/status",
    "battery_guard_state": "std_msgs/String",
    "vendor_dock_status": "std_msgs/Int32",
}

SENSOR_TOPIC_KEYS = ["scout_tof", "tof_range", "scout_imu", "imu_data"]
COMMAND_TOPIC_KEYS = ["vendor_cmd_vel", "planner_cmd_vel", "autonomy_cmd_vel", "safety_state"]
BATTERY_TOPIC_KEYS = ["battery_status", "battery_guard_state", "vendor_dock_status"]
PROBE_TOPIC_KEYS = ["lidar_scan", "camera_compressed", "odom"] + COMMAND_TOPIC_KEYS + SENSOR_TOPIC_KEYS + BATTERY_TOPIC_KEYS
REQUIRED_DYNAMIC_TF_EDGES = [("odom", "base_link")]
REQUIRED_STATIC_TF_EDGES = [("base_link", "base_laser")]
REQUIRED_TF_EDGES = REQUIRED_DYNAMIC_TF_EDGES + REQUIRED_STATIC_TF_EDGES

SERVICE_CANDIDATES = {
    "vendor_low_battery_dock": ["/nav_low_bat"],
}

SERVICE_TYPES = {
    "vendor_low_battery_dock": "roller_eye/nav_low_bat",
}

DEVICE_CANDIDATES = {
    "camera": ["/dev/video0"],
    "lidar": ["/dev/ttyS4", "/dev/ttyUSB0"],
}

TOPIC_INFO_TIMEOUT_SECONDS = 5
TOPIC_HZ_TIMEOUT_SECONDS = 6
TOPIC_SAMPLE_TIMEOUT_SECONDS = 5
TOPIC_DETAIL_TIMEOUT_BUDGET_SECONDS = (
    TOPIC_INFO_TIMEOUT_SECONDS
    + TOPIC_HZ_TIMEOUT_SECONDS
    + TOPIC_SAMPLE_TIMEOUT_SECONDS
)
TOPIC_LIST_TIMEOUT_SECONDS = 8
NODE_LIST_TIMEOUT_SECONDS = 8
SERVICE_LIST_TIMEOUT_SECONDS = 8
SERVICE_TYPE_TIMEOUT_SECONDS = 5
COMMAND_EXERCISE_TIMEOUT_BUDGET_SECONDS = 8
TF_SAMPLE_TIMEOUT_SECONDS = 5


def _format_seconds(seconds):
    value = max(float(seconds or 0.0), 0.0)
    if value < 60:
        return "{:.0f}s".format(value)
    minutes = int(value // 60)
    remainder = int(value % 60)
    return "{}m{:02d}s".format(minutes, remainder)


class ProbeProgress:
    """Format optional live probe progress without changing the JSON report."""

    def __init__(self, callback=None):
        self.callback = callback
        self.started_at = time.monotonic()
        self.completed_steps = 0
        self.total_steps = None
        self.remaining_timeout_budget = None

    def _emit(self, message):
        if not self.callback:
            return

        parts = ["elapsed {}".format(_format_seconds(time.monotonic() - self.started_at))]
        if self.total_steps:
            parts.append("{}/{} steps".format(self.completed_steps, self.total_steps))
        elif self.completed_steps:
            parts.append("{} steps done".format(self.completed_steps))
        if self.remaining_timeout_budget is not None and self.remaining_timeout_budget > 0:
            parts.append(
                "remaining ROS timeout budget <= {}".format(
                    _format_seconds(self.remaining_timeout_budget)
                )
            )
        self.callback("probe: {} ({})".format(message, ", ".join(parts)))

    def info(self, message):
        self._emit(message)

    def set_plan(self, total_steps, remaining_timeout_budget, message):
        self.total_steps = int(total_steps)
        self.remaining_timeout_budget = max(float(remaining_timeout_budget or 0.0), 0.0)
        self._emit(message)

    def begin(self, message):
        self._emit(message)

    def finish(self, message, timeout_budget=0.0):
        self.completed_steps += 1
        if self.remaining_timeout_budget is not None:
            self.remaining_timeout_budget = max(
                self.remaining_timeout_budget - float(timeout_budget or 0.0),
                0.0,
            )
        self._emit(message)


def _looks_like_local_scout():
    username = os.environ.get("USER", "")
    return any(
        [
            username == "linaro",
            Path("/home/linaro").exists(),
            Path("/usr/local/lib/librollereye.so").exists(),
            Path("/usr/bin/rollereye").exists(),
        ]
    )


def _wrap_bash(body):
    return "/bin/bash -lc {}".format(shlex.quote(body))


def _ros_shell_prefix(role_settings):
    commands = [
        "if [ -f /opt/ros/melodic/setup.bash ]; then . /opt/ros/melodic/setup.bash; fi",
        'export ROS_OS_OVERRIDE="${ROS_OS_OVERRIDE:-debian:stretch}"',
    ]
    master_uri = role_ros_setting(role_settings, "master_uri")
    advertise_host = role_ros_setting(role_settings, "advertise_host")
    if master_uri:
        commands.append("export ROS_MASTER_URI={}".format(shlex.quote(master_uri)))
    if advertise_host:
        commands.append("export ROS_HOSTNAME={}".format(shlex.quote(advertise_host)))
    return "; ".join(commands)


def _parse_env_output(text):
    values = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_rate(text):
    match = re.search(r"average rate:\s*([0-9.]+)", text or "")
    if not match:
        return None
    return float(match.group(1))


def _parse_topic_info(text):
    payload = {
        "type": None,
        "publishers": [],
        "subscribers": [],
    }
    lines = (text or "").splitlines()
    section = None
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Type:"):
            payload["type"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Publishers:"):
            section = "publishers"
            continue
        if line.startswith("Subscribers:"):
            section = "subscribers"
            continue
        if line.startswith("* ") and section:
            payload[section].append(line[2:].strip())
    return payload


def _parse_odom_snapshot(text):
    payload = {
        "frame_id": None,
        "child_frame_id": None,
        "orientation_w": None,
    }
    frame_match = re.search(r'frame_id:\s*"([^"]+)"', text or "")
    child_match = re.search(r'child_frame_id:\s*"([^"]+)"', text or "")
    orientation_match = re.search(r"orientation:\s*(?:.|\n)*?\bw:\s*([-0-9.]+)", text or "")
    if frame_match:
        payload["frame_id"] = frame_match.group(1)
    if child_match:
        payload["child_frame_id"] = child_match.group(1)
    if orientation_match:
        payload["orientation_w"] = float(orientation_match.group(1))
    return payload


def _normalize_frame_id(frame_id):
    return str(frame_id or "").strip().strip('"').lstrip("/")


def _parse_tf_edges(text):
    edges = []
    pattern = re.compile(
        r"(?m)^\s*frame_id:\s*\"?/?([^\"\n]+)\"?(?:.|\n)*?^\s*child_frame_id:\s*\"?/?([^\"\n]+)\"?"
    )
    for parent, child in pattern.findall(text or ""):
        parent = _normalize_frame_id(parent)
        child = _normalize_frame_id(child)
        if parent and child:
            edge = {"parent": parent, "child": child}
            if edge not in edges:
                edges.append(edge)
    return edges


def _edge_tuple(edge):
    return (_normalize_frame_id(edge.get("parent")), _normalize_frame_id(edge.get("child")))


def _format_tf_edges(edges):
    return [{"parent": parent, "child": child} for parent, child in sorted(edges)]


def _first_matching_keynames(fieldnames, suffixes):
    for suffix in suffixes:
        for field in fieldnames:
            if field.endswith(suffix):
                return field
    return None


def _parse_motion_csv(text):
    reader = csv.DictReader(io.StringIO(text or ""))
    fieldnames = reader.fieldnames or []
    x_key = _first_matching_keynames(fieldnames, [".pose.pose.position.x", ".twist.twist.linear.x"])
    y_key = _first_matching_keynames(fieldnames, [".pose.pose.position.y", ".twist.twist.linear.y"])
    z_key = _first_matching_keynames(fieldnames, [".pose.pose.orientation.z", ".twist.twist.angular.z"])
    rows = []
    for row in reader:
        if not row:
            continue
        try:
            rows.append(
                {
                    "x": float(row.get(x_key, 0.0) or 0.0) if x_key else 0.0,
                    "y": float(row.get(y_key, 0.0) or 0.0) if y_key else 0.0,
                    "z": float(row.get(z_key, 0.0) or 0.0) if z_key else 0.0,
                }
            )
        except ValueError:
            continue

    if len(rows) < 2:
        return {
            "samples": len(rows),
            "delta_x": 0.0,
            "delta_y": 0.0,
            "delta_z": 0.0,
            "distance": 0.0,
            "dominant_axis": "none",
            "moved": False,
        }

    delta_x = rows[-1]["x"] - rows[0]["x"]
    delta_y = rows[-1]["y"] - rows[0]["y"]
    delta_z = rows[-1]["z"] - rows[0]["z"]
    distance = math.sqrt((delta_x ** 2) + (delta_y ** 2))
    abs_x = abs(delta_x)
    abs_y = abs(delta_y)
    dominant_axis = "mixed"
    if max(abs_x, abs_y) < MOTION_DELTA_THRESHOLD:
        dominant_axis = "none"
    elif abs_x >= abs_y * 2:
        dominant_axis = "x"
    elif abs_y >= abs_x * 2:
        dominant_axis = "y"
    return {
        "samples": len(rows),
        "delta_x": delta_x,
        "delta_y": delta_y,
        "delta_z": delta_z,
        "distance": distance,
        "dominant_axis": dominant_axis,
        "moved": distance >= MOTION_DELTA_THRESHOLD or abs(delta_z) >= MOTION_DELTA_THRESHOLD,
    }


def _set_path(payload, dotted_path, value):
    parts = dotted_path.split(".")
    cursor = payload
    for item in parts[:-1]:
        cursor = cursor.setdefault(item, {})
    cursor[parts[-1]] = value


class ProbeExecutor:
    """Run commands locally or over SSH for Scout probing."""

    def __init__(self, role_settings, runner=None, force_remote=False):
        self.role_settings = role_settings
        self.runner = runner or CommandRunner()
        self.force_remote = force_remote
        self.use_remote = bool(force_remote or not _looks_like_local_scout())

    def run(self, body, check=False):
        command = _wrap_bash("{}; {}".format(_ros_shell_prefix(self.role_settings), body))
        if not self.use_remote:
            return self.runner.run(command, check=check)

        ssh = self.role_settings.get("ssh", {})
        return self.runner.run_remote(ssh, command, check=check)


def _candidate_topics(role_settings, key):
    configured = role_topic(role_settings, key)
    values = []
    for item in [configured] + TOPIC_CANDIDATES.get(key, []):
        if item and item not in values:
            values.append(item)
    return values


def _candidate_devices(role_settings, key):
    configured = role_device(role_settings, key)
    values = []
    for item in [configured] + DEVICE_CANDIDATES.get(key, []):
        if item and item not in values:
            values.append(item)
    return values


def _candidate_services(key):
    return list(SERVICE_CANDIDATES.get(key, []))


def _device_exists(executor, path):
    result = executor.run("test -e {} && echo present || echo missing".format(shlex.quote(path)), check=False)
    return result.ok and "present" in result.stdout


def _check_device(executor, path, candidates=None):
    payload = {
        "configured": path,
        "exists": None,
        "selected": None,
        "alternatives": [],
    }
    if path:
        payload["exists"] = _device_exists(executor, path)
        if payload["exists"]:
            payload["selected"] = path

    for candidate in candidates or []:
        if not candidate or candidate == path:
            continue
        if _device_exists(executor, candidate):
            payload["alternatives"].append(candidate)
            if payload["selected"] is None:
                payload["selected"] = candidate
    return payload


def _topic_details(executor, topic_name, progress=None, topic_key=None):
    label = "{} {}".format(topic_key, topic_name) if topic_key else topic_name
    if progress:
        progress.begin(
            "Topic {}: reading publishers/subscribers (timeout {}s)".format(
                label,
                TOPIC_INFO_TIMEOUT_SECONDS,
            )
        )
    info = executor.run(
        "timeout {}s rostopic info {}".format(
            TOPIC_INFO_TIMEOUT_SECONDS,
            shlex.quote(topic_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "Topic {}: info complete".format(label),
            timeout_budget=TOPIC_INFO_TIMEOUT_SECONDS,
        )
    topic_info = _parse_topic_info(info.stdout)
    if progress:
        progress.begin(
            "Topic {}: measuring rate (timeout {}s)".format(
                label,
                TOPIC_HZ_TIMEOUT_SECONDS,
            )
        )
    rate = executor.run(
        "timeout {}s rostopic hz -w 5 {}".format(
            TOPIC_HZ_TIMEOUT_SECONDS,
            shlex.quote(topic_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "Topic {}: rate check complete".format(label),
            timeout_budget=TOPIC_HZ_TIMEOUT_SECONDS,
        )
    if progress:
        progress.begin(
            "Topic {}: sampling one message (timeout {}s)".format(
                label,
                TOPIC_SAMPLE_TIMEOUT_SECONDS,
            )
        )
    sample = executor.run(
        "timeout {}s rostopic echo -n 1 {}".format(
            TOPIC_SAMPLE_TIMEOUT_SECONDS,
            shlex.quote(topic_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "Topic {}: sample complete".format(label),
            timeout_budget=TOPIC_SAMPLE_TIMEOUT_SECONDS,
        )
    return {
        "name": topic_name,
        "available": info.ok and bool(topic_info.get("type")),
        "type": topic_info.get("type"),
        "publishers": topic_info.get("publishers", []),
        "subscribers": topic_info.get("subscribers", []),
        "hz": _parse_rate(rate.stdout),
        "sample": sample.stdout,
    }


def _tf_topic_details(executor, topic_name, progress=None, label=None):
    topic_label = label or topic_name
    if progress:
        progress.begin(
            "TF {}: reading publishers/subscribers (timeout {}s)".format(
                topic_label,
                TOPIC_INFO_TIMEOUT_SECONDS,
            )
        )
    info = executor.run(
        "timeout {}s rostopic info {}".format(
            TOPIC_INFO_TIMEOUT_SECONDS,
            shlex.quote(topic_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "TF {}: info complete".format(topic_label),
            timeout_budget=TOPIC_INFO_TIMEOUT_SECONDS,
        )
    topic_info = _parse_topic_info(info.stdout)

    if progress:
        progress.begin(
            "TF {}: sampling transforms (timeout {}s)".format(
                topic_label,
                TF_SAMPLE_TIMEOUT_SECONDS,
            )
        )
    sample = executor.run(
        "timeout {}s rostopic echo {}".format(
            TF_SAMPLE_TIMEOUT_SECONDS,
            shlex.quote(topic_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "TF {}: sample complete".format(topic_label),
            timeout_budget=TF_SAMPLE_TIMEOUT_SECONDS,
        )
    return {
        "name": topic_name,
        "available": info.ok and topic_info.get("type") == "tf2_msgs/TFMessage",
        "type": topic_info.get("type"),
        "publishers": topic_info.get("publishers", []),
        "subscribers": topic_info.get("subscribers", []),
        "edges": _parse_tf_edges(sample.stdout),
        "sample": sample.stdout,
    }


def _tf_details(executor, topic_names, progress=None):
    dynamic = None
    static = None
    if "/tf" in topic_names:
        dynamic = _tf_topic_details(executor, "/tf", progress=progress, label="/tf")
    if "/tf_static" in topic_names:
        static = _tf_topic_details(executor, "/tf_static", progress=progress, label="/tf_static")

    dynamic_edges = set(_edge_tuple(edge) for edge in (dynamic or {}).get("edges", []))
    static_edges = set(_edge_tuple(edge) for edge in (static or {}).get("edges", []))
    observed_edges = dynamic_edges.union(static_edges)
    required_edges = set(REQUIRED_TF_EDGES)
    missing_dynamic_edges = set(REQUIRED_DYNAMIC_TF_EDGES).difference(dynamic_edges)
    missing_static_edges = set(REQUIRED_STATIC_TF_EDGES).difference(static_edges)
    missing_edges = missing_dynamic_edges.union(missing_static_edges)
    return {
        "ok": not missing_edges,
        "required_edges": _format_tf_edges(required_edges),
        "observed_edges": _format_tf_edges(observed_edges),
        "missing_edges": _format_tf_edges(missing_edges),
        "missing_dynamic_edges": _format_tf_edges(missing_dynamic_edges),
        "missing_static_edges": _format_tf_edges(missing_static_edges),
        "dynamic": dynamic
        or {
            "name": "/tf",
            "available": False,
            "type": None,
            "publishers": [],
            "subscribers": [],
            "edges": [],
            "sample": "",
        },
        "static": static
        or {
            "name": "/tf_static",
            "available": False,
            "type": None,
            "publishers": [],
            "subscribers": [],
            "edges": [],
            "sample": "",
        },
    }


def _service_details(executor, service_name, progress=None, service_key=None):
    label = "{} {}".format(service_key, service_name) if service_key else service_name
    if progress:
        progress.begin(
            "Service {}: reading type (timeout {}s)".format(
                label,
                SERVICE_TYPE_TIMEOUT_SECONDS,
            )
        )
    result = executor.run(
        "timeout {}s rosservice type {}".format(
            SERVICE_TYPE_TIMEOUT_SECONDS,
            shlex.quote(service_name),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "Service {}: type check complete".format(label),
            timeout_budget=SERVICE_TYPE_TIMEOUT_SECONDS,
        )
    service_type = (result.stdout or "").strip() if result.ok else None
    return {
        "name": service_name,
        "available": result.ok and bool(service_type),
        "type": service_type,
    }


def _observe_motion_timeout(seconds):
    return max(int(seconds) + 2, 3)


def _observe_topic_motion(executor, odom_topic, seconds, progress=None):
    timeout = _observe_motion_timeout(seconds)
    if progress:
        progress.begin(
            "Observing odometry motion on {} for {}s (timeout {}s)".format(
                odom_topic,
                seconds,
                timeout,
            )
        )
    observed = executor.run(
        "timeout {timeout}s rostopic echo -p {topic}".format(
            timeout=timeout,
            topic=shlex.quote(odom_topic),
        ),
        check=False,
    )
    if progress:
        progress.finish(
            "Motion observation complete",
            timeout_budget=timeout,
        )
    series = _parse_motion_csv(observed.stdout)
    series["duration_seconds"] = seconds
    return series


def _exercise_motion(executor, odom_topic, cmd_topic, forward_axis, progress=None):
    linear_x = 0.0
    linear_y = 0.0
    if forward_axis == "x":
        linear_x = 0.08
    else:
        linear_y = 0.08

    command = """
tmp_file="$(mktemp)"
(timeout 5s rostopic echo -p {odom_topic} > "${{tmp_file}}" ) &
echo_pid=$!
sleep 1
timeout 2s rostopic pub -r 10 {cmd_topic} geometry_msgs/Twist \
'{{linear: {{x: {linear_x}, y: {linear_y}, z: 0.0}}, angular: {{x: 0.0, y: 0.0, z: 0.0}}}}' >/dev/null 2>&1 || true
sleep 1
wait "${{echo_pid}}" || true
cat "${{tmp_file}}"
rm -f "${{tmp_file}}"
""".format(
        odom_topic=shlex.quote(odom_topic),
        cmd_topic=shlex.quote(cmd_topic),
        linear_x=linear_x,
        linear_y=linear_y,
    )
    if progress:
        progress.begin(
            "Exercising vendor command topic {} while observing {}".format(
                cmd_topic,
                odom_topic,
            )
        )
    observed = executor.run(command, check=False)
    if progress:
        progress.finish(
            "Vendor command exercise complete",
            timeout_budget=COMMAND_EXERCISE_TIMEOUT_BUDGET_SECONDS,
        )
    payload = _parse_motion_csv(observed.stdout)
    payload["command_topic"] = cmd_topic
    payload["forward_axis"] = forward_axis
    return payload


def _compare_site_config(site_config, observed, inferred_capabilities):
    scout = role_config(site_config, "scout")
    suggestions = []

    for device_name in ["camera", "lidar"]:
        observed_device = observed.get("devices", {}).get(device_name, {})
        suggested = observed_device.get("selected")
        current = role_device(scout, device_name)
        if not suggested or current == suggested:
            continue

        reason = "Live probe found Scout {} device '{}'.".format(device_name, suggested)
        if current and not observed_device.get("exists"):
            reason = "Configured Scout {} device '{}' was missing; live probe found '{}'.".format(
                device_name,
                current,
                suggested,
            )
        suggestions.append(
            {
                "path": "roles.scout.devices.{}".format(device_name),
                "current": current,
                "suggested": suggested,
                "reason": reason,
            }
        )

    for topic_key in ["odom", "vendor_cmd_vel", "lidar_scan", "camera_compressed"] + SENSOR_TOPIC_KEYS:
        observed_topic = observed.get("topics", {}).get(topic_key, {})
        suggested = observed_topic.get("selected")
        current = role_topic(scout, topic_key)
        if suggested and current != suggested:
            suggestions.append(
                {
                    "path": "roles.scout.topics.{}".format(topic_key),
                    "current": current,
                    "suggested": suggested,
                    "reason": "Live probe found '{}' on the Scout ROS graph.".format(suggested),
                }
            )

    for capability_name, suggested in inferred_capabilities.items():
        if suggested is None:
            continue
        current = scout.get("capabilities", {}).get(capability_name)
        if current != suggested:
            suggestions.append(
                {
                    "path": "roles.scout.capabilities.{}".format(capability_name),
                    "current": current,
                    "suggested": suggested,
                    "reason": "Live probe {} '{}'.".format(
                        "confirmed" if suggested else "did not confirm",
                        capability_name,
                    ),
                }
            )

    env = observed.get("ros_environment", {})
    current_master = role_ros_setting(scout, "master_uri")
    if env.get("ROS_MASTER_URI") and env["ROS_MASTER_URI"] != current_master:
        suggestions.append(
            {
                "path": "roles.scout.ros.master_uri",
                "current": current_master,
                "suggested": env["ROS_MASTER_URI"],
                "reason": "The live Scout shell reports a different ROS master URI.",
            }
        )
    current_advertise = role_ros_setting(scout, "advertise_host")
    advertised = env.get("ROS_HOSTNAME") or env.get("ROS_IP")
    if advertised and advertised != current_advertise:
        suggestions.append(
            {
                "path": "roles.scout.ros.advertise_host",
                "current": current_advertise,
                "suggested": advertised,
                "reason": "The live Scout shell reports a different advertised ROS host.",
            }
        )

    return suggestions


def apply_probe_suggestions(site_config, probe_result):
    """Return an updated site config with probe suggestions applied."""
    updated = deepcopy(site_config)
    for item in probe_result.get("config_mismatch_suggestions", []):
        if item.get("suggested") is None:
            continue
        _set_path(updated, item["path"], item["suggested"])
    return updated


def probe_scout_capabilities(
    site_config,
    observe_motion_seconds=DEFAULT_OBSERVE_MOTION_SECONDS,
    exercise_cmd_vel=False,
    runner=None,
    artifact_run=None,
    force_remote=False,
    progress=None,
):
    """Probe the live Scout ROS surface and infer capabilities."""
    scout = role_config(site_config, "scout")
    executor = ProbeExecutor(scout, runner=runner or CommandRunner(artifact_run=artifact_run), force_remote=force_remote)
    progress_tracker = ProbeProgress(progress)
    payload = {
        "ok": False,
        "mode": "ssh" if executor.use_remote else "local",
        "observed": {
            "ros_environment": {},
            "devices": {},
            "topics": {},
            "tf": {},
            "services": {},
            "nodes": [],
            "motion_observation": None,
            "command_exercise": None,
        },
        "inferred_capabilities": {
            "camera": None,
            "scan": None,
            "tof": None,
            "imu": None,
            "pose": None,
            "motion": None,
            "vendor_bridge": None,
        },
        "config_mismatch_suggestions": [],
        "errors": [],
    }

    progress_tracker.info("Starting live Scout probe in {} mode".format(payload["mode"]))
    progress_tracker.begin("Reading ROS environment")
    env_result = executor.run(
        "printf 'ROS_MASTER_URI=%s\nROS_HOSTNAME=%s\nROS_IP=%s\n' \"$ROS_MASTER_URI\" \"$ROS_HOSTNAME\" \"$ROS_IP\"",
        check=False,
    )
    payload["observed"]["ros_environment"] = _parse_env_output(env_result.stdout)
    progress_tracker.finish("ROS environment captured")

    progress_tracker.begin(
        "Listing ROS topics (timeout {}s)".format(TOPIC_LIST_TIMEOUT_SECONDS)
    )
    topic_list_result = executor.run(
        "timeout {}s rostopic list".format(TOPIC_LIST_TIMEOUT_SECONDS),
        check=False,
    )
    if not topic_list_result.ok:
        payload["errors"].append("rostopic list failed: {}".format(topic_list_result.stderr.strip() or "unavailable"))
        progress_tracker.finish(
            "ROS topic list failed; ending probe",
            timeout_budget=TOPIC_LIST_TIMEOUT_SECONDS,
        )
        return payload
    progress_tracker.finish(
        "ROS topic list captured",
        timeout_budget=TOPIC_LIST_TIMEOUT_SECONDS,
    )

    topic_names = {line.strip() for line in topic_list_result.stdout.splitlines() if line.strip()}
    progress_tracker.begin(
        "Listing ROS nodes (timeout {}s)".format(NODE_LIST_TIMEOUT_SECONDS)
    )
    node_list_result = executor.run(
        "timeout {}s rosnode list".format(NODE_LIST_TIMEOUT_SECONDS),
        check=False,
    )
    payload["observed"]["nodes"] = [line.strip() for line in node_list_result.stdout.splitlines() if line.strip()]
    progress_tracker.finish(
        "ROS node list captured",
        timeout_budget=NODE_LIST_TIMEOUT_SECONDS,
    )
    progress_tracker.begin(
        "Listing ROS services (timeout {}s)".format(SERVICE_LIST_TIMEOUT_SECONDS)
    )
    service_list_result = executor.run(
        "timeout {}s rosservice list".format(SERVICE_LIST_TIMEOUT_SECONDS),
        check=False,
    )
    service_names = {line.strip() for line in service_list_result.stdout.splitlines() if line.strip()} if service_list_result.ok else set()
    progress_tracker.finish(
        "ROS service list captured" if service_list_result.ok else "ROS service list unavailable; continuing without services",
        timeout_budget=SERVICE_LIST_TIMEOUT_SECONDS,
    )

    selected_topics = {}
    for topic_key in PROBE_TOPIC_KEYS:
        topic_entry = {
            "configured": role_topic(scout, topic_key),
            "selected": None,
            "details": None,
        }
        for candidate in _candidate_topics(scout, topic_key):
            if candidate in topic_names:
                topic_entry["selected"] = candidate
                break
        payload["observed"]["topics"][topic_key] = topic_entry
        selected_topics[topic_key] = topic_entry["selected"]

    selected_services = {}
    for service_key in SERVICE_CANDIDATES:
        service_entry = {
            "selected": None,
            "details": None,
        }
        for candidate in _candidate_services(service_key):
            if candidate in service_names:
                service_entry["selected"] = candidate
                break
        payload["observed"]["services"][service_key] = service_entry
        selected_services[service_key] = service_entry["selected"]

    selected_topic_count = len([topic for topic in selected_topics.values() if topic])
    selected_service_count = len([service for service in selected_services.values() if service])
    device_names = ["camera", "lidar"]
    device_step_count = len(device_names)
    motion_observation_will_run = bool(observe_motion_seconds and selected_topics.get("odom"))
    command_exercise_will_run = bool(
        exercise_cmd_vel and selected_topics.get("odom") and selected_topics.get("vendor_cmd_vel")
    )
    future_steps = (
        device_step_count
        + (selected_topic_count * 3)
        + selected_service_count
        + (2 if "/tf" in topic_names else 0)
        + (2 if "/tf_static" in topic_names else 0)
        + 1
        + 1
        + 1
    )
    timeout_budget = (
        selected_topic_count * TOPIC_DETAIL_TIMEOUT_BUDGET_SECONDS
        + selected_service_count * SERVICE_TYPE_TIMEOUT_SECONDS
        + (TOPIC_INFO_TIMEOUT_SECONDS + TF_SAMPLE_TIMEOUT_SECONDS if "/tf" in topic_names else 0)
        + (TOPIC_INFO_TIMEOUT_SECONDS + TF_SAMPLE_TIMEOUT_SECONDS if "/tf_static" in topic_names else 0)
    )
    if motion_observation_will_run:
        timeout_budget += _observe_motion_timeout(observe_motion_seconds)
    if command_exercise_will_run:
        timeout_budget += COMMAND_EXERCISE_TIMEOUT_BUDGET_SECONDS
    progress_tracker.set_plan(
        progress_tracker.completed_steps + future_steps,
        timeout_budget,
        "Probe work plan: {} topic groups selected, {} services selected".format(
            selected_topic_count,
            selected_service_count,
        ),
    )

    for device_name in device_names:
        progress_tracker.begin("Checking Scout {} device candidates".format(device_name))
        payload["observed"]["devices"][device_name] = _check_device(
            executor,
            role_device(scout, device_name),
            candidates=_candidate_devices(scout, device_name),
        )
        progress_tracker.finish("Scout {} device check complete".format(device_name))

    for topic_key in PROBE_TOPIC_KEYS:
        selected_topic = selected_topics[topic_key]
        if not selected_topic:
            progress_tracker.info("Topic {} was not found in the ROS graph".format(topic_key))
            continue
        payload["observed"]["topics"][topic_key]["details"] = _topic_details(
            executor,
            selected_topic,
            progress=progress_tracker,
            topic_key=topic_key,
        )

    payload["observed"]["tf"] = _tf_details(executor, topic_names, progress=progress_tracker)

    for service_key in SERVICE_CANDIDATES:
        selected_service = selected_services[service_key]
        if not selected_service:
            progress_tracker.info("Service {} was not found in the ROS graph".format(service_key))
            continue
        payload["observed"]["services"][service_key]["details"] = _service_details(
            executor,
            selected_service,
            progress=progress_tracker,
            service_key=service_key,
        )

    odom_details = payload["observed"]["topics"]["odom"].get("details") or {}
    if odom_details.get("sample"):
        odom_details["snapshot"] = _parse_odom_snapshot(odom_details["sample"])

    if observe_motion_seconds and selected_topics.get("odom"):
        payload["observed"]["motion_observation"] = _observe_topic_motion(
            executor,
            selected_topics["odom"],
            observe_motion_seconds,
            progress=progress_tracker,
        )
    elif observe_motion_seconds:
        progress_tracker.finish("Motion observation skipped because no odom topic was selected")
    else:
        progress_tracker.finish("Motion observation skipped (--observe-motion 0)")

    if exercise_cmd_vel and selected_topics.get("odom") and selected_topics.get("vendor_cmd_vel"):
        payload["observed"]["command_exercise"] = _exercise_motion(
            executor,
            selected_topics["odom"],
            selected_topics["vendor_cmd_vel"],
            role_motion_setting(scout, "forward_axis", "y"),
            progress=progress_tracker,
        )
    elif exercise_cmd_vel:
        progress_tracker.finish("Vendor command exercise skipped because odom or vendor command topic was missing")
    else:
        progress_tracker.finish("Vendor command exercise skipped (--exercise-cmd-vel not set)")

    progress_tracker.begin("Inferring capabilities and site-inventory suggestions")
    lidar_details = payload["observed"]["topics"]["lidar_scan"].get("details") or {}
    camera_details = payload["observed"]["topics"]["camera_compressed"].get("details") or {}
    scout_tof_details = payload["observed"]["topics"]["scout_tof"].get("details") or {}
    tof_range_details = payload["observed"]["topics"]["tof_range"].get("details") or {}
    scout_imu_details = payload["observed"]["topics"]["scout_imu"].get("details") or {}
    imu_data_details = payload["observed"]["topics"]["imu_data"].get("details") or {}
    payload["inferred_capabilities"]["scan"] = bool(
        selected_topics.get("lidar_scan") and lidar_details.get("type") == TOPIC_TYPES["lidar_scan"]
    )
    payload["inferred_capabilities"]["camera"] = bool(
        selected_topics.get("camera_compressed") or payload["observed"]["devices"]["camera"].get("exists")
    )
    payload["inferred_capabilities"]["tof"] = bool(
        (
            selected_topics.get("scout_tof")
            and scout_tof_details.get("type") == TOPIC_TYPES["scout_tof"]
        )
        or (
            selected_topics.get("tof_range")
            and tof_range_details.get("type") == TOPIC_TYPES["tof_range"]
        )
    )
    payload["inferred_capabilities"]["imu"] = bool(
        (
            selected_topics.get("scout_imu")
            and scout_imu_details.get("type") == TOPIC_TYPES["scout_imu"]
        )
        or (
            selected_topics.get("imu_data")
            and imu_data_details.get("type") == TOPIC_TYPES["imu_data"]
        )
    )
    payload["inferred_capabilities"]["vendor_bridge"] = "/MotorNode" in payload["observed"]["nodes"]

    if selected_topics.get("odom") and odom_details.get("type") == TOPIC_TYPES["odom"]:
        if payload["observed"]["motion_observation"] is not None:
            payload["inferred_capabilities"]["pose"] = bool(payload["observed"]["motion_observation"].get("moved"))
    else:
        payload["inferred_capabilities"]["pose"] = False

    if exercise_cmd_vel:
        exercise = payload["observed"]["command_exercise"] or {}
        payload["inferred_capabilities"]["motion"] = bool(exercise.get("moved"))

    payload["config_mismatch_suggestions"] = _compare_site_config(
        site_config,
        payload["observed"],
        payload["inferred_capabilities"],
    )
    payload["ok"] = True
    progress_tracker.finish("Live Scout probe complete")
    return payload

"""Live Scout capability probing and site-inventory reconciliation."""

import csv
import io
import math
import os
import re
import shlex
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
    "odom": ["/MotorNode/baselink_odom_relative", "/MotorNode/vio_odom_relative", "/odom"],
    "vendor_cmd_vel": ["/cmd_vel_force", "/cmd_vel"],
}

TOPIC_TYPES = {
    "lidar_scan": "sensor_msgs/LaserScan",
    "camera_compressed": "sensor_msgs/CompressedImage",
    "odom": "nav_msgs/Odometry",
    "vendor_cmd_vel": "geometry_msgs/Twist",
}

DEVICE_CANDIDATES = {
    "camera": ["/dev/video0"],
    "lidar": ["/dev/ttyS4", "/dev/ttyUSB0"],
}


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


def _topic_details(executor, topic_name):
    info = executor.run("rostopic info {}".format(shlex.quote(topic_name)), check=False)
    topic_info = _parse_topic_info(info.stdout)
    rate = executor.run(
        "timeout 6s rostopic hz -w 5 {}".format(shlex.quote(topic_name)),
        check=False,
    )
    sample = executor.run(
        "timeout 5s rostopic echo -n 1 {}".format(shlex.quote(topic_name)),
        check=False,
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


def _observe_topic_motion(executor, odom_topic, seconds):
    observed = executor.run(
        "timeout {timeout}s rostopic echo -p {topic}".format(
            timeout=max(int(seconds) + 2, 3),
            topic=shlex.quote(odom_topic),
        ),
        check=False,
    )
    series = _parse_motion_csv(observed.stdout)
    series["duration_seconds"] = seconds
    return series


def _exercise_motion(executor, odom_topic, cmd_topic, forward_axis):
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
    observed = executor.run(command, check=False)
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

    for topic_key in ["odom", "vendor_cmd_vel", "lidar_scan", "camera_compressed"]:
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
):
    """Probe the live Scout ROS surface and infer capabilities."""
    scout = role_config(site_config, "scout")
    executor = ProbeExecutor(scout, runner=runner or CommandRunner(artifact_run=artifact_run), force_remote=force_remote)
    payload = {
        "ok": False,
        "mode": "ssh" if executor.use_remote else "local",
        "observed": {
            "ros_environment": {},
            "devices": {},
            "topics": {},
            "nodes": [],
            "motion_observation": None,
            "command_exercise": None,
        },
        "inferred_capabilities": {
            "camera": None,
            "scan": None,
            "pose": None,
            "motion": None,
            "vendor_bridge": None,
        },
        "config_mismatch_suggestions": [],
        "errors": [],
    }

    env_result = executor.run(
        "printf 'ROS_MASTER_URI=%s\nROS_HOSTNAME=%s\nROS_IP=%s\n' \"$ROS_MASTER_URI\" \"$ROS_HOSTNAME\" \"$ROS_IP\"",
        check=False,
    )
    payload["observed"]["ros_environment"] = _parse_env_output(env_result.stdout)

    topic_list_result = executor.run("rostopic list", check=False)
    if not topic_list_result.ok:
        payload["errors"].append("rostopic list failed: {}".format(topic_list_result.stderr.strip() or "unavailable"))
        return payload

    topic_names = {line.strip() for line in topic_list_result.stdout.splitlines() if line.strip()}
    node_list_result = executor.run("rosnode list", check=False)
    payload["observed"]["nodes"] = [line.strip() for line in node_list_result.stdout.splitlines() if line.strip()]

    for device_name in ["camera", "lidar"]:
        payload["observed"]["devices"][device_name] = _check_device(
            executor,
            role_device(scout, device_name),
            candidates=_candidate_devices(scout, device_name),
        )

    selected_topics = {}
    for topic_key in ["lidar_scan", "camera_compressed", "odom", "vendor_cmd_vel"]:
        topic_entry = {
            "configured": role_topic(scout, topic_key),
            "selected": None,
            "details": None,
        }
        for candidate in _candidate_topics(scout, topic_key):
            if candidate in topic_names:
                topic_entry["selected"] = candidate
                topic_entry["details"] = _topic_details(executor, candidate)
                break
        payload["observed"]["topics"][topic_key] = topic_entry
        selected_topics[topic_key] = topic_entry["selected"]

    odom_details = payload["observed"]["topics"]["odom"].get("details") or {}
    if odom_details.get("sample"):
        odom_details["snapshot"] = _parse_odom_snapshot(odom_details["sample"])

    if observe_motion_seconds and selected_topics.get("odom"):
        payload["observed"]["motion_observation"] = _observe_topic_motion(
            executor,
            selected_topics["odom"],
            observe_motion_seconds,
        )

    if exercise_cmd_vel and selected_topics.get("odom") and selected_topics.get("vendor_cmd_vel"):
        payload["observed"]["command_exercise"] = _exercise_motion(
            executor,
            selected_topics["odom"],
            selected_topics["vendor_cmd_vel"],
            role_motion_setting(scout, "forward_axis", "y"),
        )

    lidar_details = payload["observed"]["topics"]["lidar_scan"].get("details") or {}
    camera_details = payload["observed"]["topics"]["camera_compressed"].get("details") or {}
    payload["inferred_capabilities"]["scan"] = bool(
        selected_topics.get("lidar_scan") and lidar_details.get("type") == TOPIC_TYPES["lidar_scan"]
    )
    payload["inferred_capabilities"]["camera"] = bool(
        selected_topics.get("camera_compressed") or payload["observed"]["devices"]["camera"].get("exists")
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
    return payload

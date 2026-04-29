"""Unit tests for live Scout probing helpers."""

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auto_scout.live_probe import apply_probe_suggestions, probe_scout_capabilities
from auto_scout.site_config import default_site_config


class FakeCommandResult:
    """Small stand-in for CommandRunner results."""

    def __init__(self, ok=True, stdout="", stderr=""):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Deterministic command runner for probe unit tests."""

    def __init__(self, overrides=None):
        self.commands = []
        self.lookup = {
            "printf 'ROS_MASTER_URI=%s": FakeCommandResult(
                stdout="ROS_MASTER_URI=http://scout.example.test:11311\nROS_HOSTNAME=scout.example.test\nROS_IP=\n",
            ),
            "rostopic list": FakeCommandResult(
                stdout=(
                    "/scan\n"
                    "/camera/image_raw/compressed\n"
                    "/SensorNode/tof\n"
                    "/scout/tof\n"
                    "/SensorNode/imu\n"
                    "/scout/imu/data\n"
                    "/MotorNode/baselink_odom_relative\n"
                    "/cmd_vel_force\n"
                    "/scout/cmd_vel_planner\n"
                    "/scout/cmd_vel_companion\n"
                    "/scout/safety_state\n"
                    "/tf_static\n"
                    "/tf\n"
                    "/SensorNode/simple_battery_status\n"
                    "/scout/battery_guard_state\n"
                    "/CoreNode/going_home_status\n"
                ),
            ),
            "rosnode list": FakeCommandResult(stdout="/MotorNode\n"),
            "rosservice list": FakeCommandResult(stdout="/nav_low_bat\n"),
            "rosservice type /nav_low_bat": FakeCommandResult(stdout="roller_eye/nav_low_bat\n"),
            "test -e /dev/video0": FakeCommandResult(stdout="present\n"),
            "test -e /dev/ttyS4": FakeCommandResult(stdout="present\n"),
            "test -e /dev/ttyUSB0": FakeCommandResult(stdout="missing\n"),
            "rostopic info /scan": FakeCommandResult(stdout="Type: sensor_msgs/LaserScan\nPublishers:\n * /ld19\nSubscribers:\n"),
            "rostopic hz -w 5 /scan": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /scan": FakeCommandResult(stdout="header:\n"),
            "rostopic info /camera/image_raw/compressed": FakeCommandResult(stdout="Type: sensor_msgs/CompressedImage\nPublishers:\n * /camera\nSubscribers:\n"),
            "rostopic hz -w 5 /camera/image_raw/compressed": FakeCommandResult(ok=False, stdout="average rate: 5.0\n"),
            "rostopic echo -n 1 /camera/image_raw/compressed": FakeCommandResult(stdout="header:\n"),
            "rostopic info /SensorNode/tof": FakeCommandResult(stdout="Type: sensor_msgs/Range\nPublishers:\n * /SensorNode\nSubscribers:\n"),
            "rostopic hz -w 5 /SensorNode/tof": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /SensorNode/tof": FakeCommandResult(stdout="range: 0.5\n"),
            "rostopic info /scout/tof": FakeCommandResult(stdout="Type: sensor_msgs/Range\nPublishers:\n * /scout_tof_bridge\nSubscribers:\n"),
            "rostopic hz -w 5 /scout/tof": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /scout/tof": FakeCommandResult(stdout="range: 0.5\n"),
            "rostopic info /SensorNode/imu": FakeCommandResult(stdout="Type: sensor_msgs/Imu\nPublishers:\n * /SensorNode\nSubscribers:\n"),
            "rostopic hz -w 5 /SensorNode/imu": FakeCommandResult(ok=False, stdout="average rate: 50.0\n"),
            "rostopic echo -n 1 /SensorNode/imu": FakeCommandResult(stdout="orientation:\n  w: 1.0\n"),
            "rostopic info /scout/imu/data": FakeCommandResult(stdout="Type: sensor_msgs/Imu\nPublishers:\n * /scout_imu_bridge\nSubscribers:\n"),
            "rostopic hz -w 5 /scout/imu/data": FakeCommandResult(ok=False, stdout="average rate: 50.0\n"),
            "rostopic echo -n 1 /scout/imu/data": FakeCommandResult(stdout="orientation:\n  w: 1.0\n"),
            "rostopic info /MotorNode/baselink_odom_relative": FakeCommandResult(stdout="Type: nav_msgs/Odometry\nPublishers:\n * /MotorNode\nSubscribers:\n"),
            "rostopic hz -w 5 /MotorNode/baselink_odom_relative": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /MotorNode/baselink_odom_relative": FakeCommandResult(
                stdout='header:\n  frame_id: "world"\nchild_frame_id: "base_link"\npose:\n  pose:\n    orientation:\n      w: 1.0\n',
            ),
            "rostopic info /MotorNode/vio_odom_relative": FakeCommandResult(stdout="Type: nav_msgs/Odometry\nPublishers:\n * /MotorNode\nSubscribers:\n"),
            "rostopic hz -w 5 /MotorNode/vio_odom_relative": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /MotorNode/vio_odom_relative": FakeCommandResult(
                stdout='header:\n  frame_id: "world"\nchild_frame_id: "base_link"\npose:\n  pose:\n    orientation:\n      w: 1.0\n',
            ),
            "rostopic info /cmd_vel_force": FakeCommandResult(stdout="Type: geometry_msgs/Twist\nPublishers:\nSubscribers:\n * /MotorNode\n"),
            "rostopic hz -w 5 /cmd_vel_force": FakeCommandResult(ok=False, stdout="average rate: 0.0\n"),
            "rostopic echo -n 1 /cmd_vel_force": FakeCommandResult(stdout="linear:\n  x: 0.0\n"),
            "rostopic info /scout/cmd_vel_planner": FakeCommandResult(stdout="Type: geometry_msgs/Twist\nPublishers:\nSubscribers:\n * /scout_safety_filter\n"),
            "rostopic hz -w 5 /scout/cmd_vel_planner": FakeCommandResult(ok=False, stdout="average rate: 0.0\n"),
            "rostopic echo -n 1 /scout/cmd_vel_planner": FakeCommandResult(stdout="linear:\n  x: 0.0\n"),
            "rostopic info /scout/cmd_vel_companion": FakeCommandResult(stdout="Type: geometry_msgs/Twist\nPublishers:\n * /scout_safety_filter\nSubscribers:\n * /scout_motion_bridge\n"),
            "rostopic hz -w 5 /scout/cmd_vel_companion": FakeCommandResult(ok=False, stdout="average rate: 0.0\n"),
            "rostopic echo -n 1 /scout/cmd_vel_companion": FakeCommandResult(stdout="linear:\n  x: 0.0\n"),
            "rostopic info /scout/safety_state": FakeCommandResult(stdout="Type: std_msgs/String\nPublishers:\n * /scout_safety_filter\nSubscribers:\n"),
            "rostopic hz -w 5 /scout/safety_state": FakeCommandResult(ok=False, stdout="average rate: 1.0\n"),
            "rostopic echo -n 1 /scout/safety_state": FakeCommandResult(stdout='data: "{\\"state\\": \\"clear\\"}"\n'),
            "rostopic info /tf_static": FakeCommandResult(stdout="Type: tf2_msgs/TFMessage\nPublishers:\n * /robot_state_publisher\nSubscribers:\n"),
            "rostopic echo /tf_static": FakeCommandResult(
                stdout='transforms:\n  -\n    header:\n      frame_id: "base_link"\n    child_frame_id: "base_laser"\n',
            ),
            "rostopic info /tf": FakeCommandResult(stdout="Type: tf2_msgs/TFMessage\nPublishers:\n * /scout_odom_bridge\nSubscribers:\n"),
            "rostopic echo /tf": FakeCommandResult(
                stdout='transforms:\n  -\n    header:\n      frame_id: "odom"\n    child_frame_id: "base_link"\n',
            ),
            "rostopic info /SensorNode/simple_battery_status": FakeCommandResult(stdout="Type: roller_eye/status\nPublishers:\n * /SensorNode\nSubscribers:\n * /scout_battery_dock_guard\n"),
            "rostopic hz -w 5 /SensorNode/simple_battery_status": FakeCommandResult(ok=False, stdout="average rate: 1.0\n"),
            "rostopic echo -n 1 /SensorNode/simple_battery_status": FakeCommandResult(stdout="status: [0, 82, 0]\n"),
            "rostopic info /scout/battery_guard_state": FakeCommandResult(stdout="Type: std_msgs/String\nPublishers:\n * /scout_battery_dock_guard\nSubscribers:\n * /scout_safety_filter\n"),
            "rostopic hz -w 5 /scout/battery_guard_state": FakeCommandResult(ok=False, stdout="average rate: 1.0\n"),
            "rostopic echo -n 1 /scout/battery_guard_state": FakeCommandResult(stdout='data: "{\\"mode\\": \\"idle\\"}"\n'),
            "rostopic info /CoreNode/going_home_status": FakeCommandResult(stdout="Type: std_msgs/Int32\nPublishers:\n * /CoreNode\nSubscribers:\n * /scout_battery_dock_guard\n"),
            "rostopic hz -w 5 /CoreNode/going_home_status": FakeCommandResult(ok=False, stdout="average rate: 0.0\n"),
            "rostopic echo -n 1 /CoreNode/going_home_status": FakeCommandResult(stdout="data: 6\n"),
            "timeout 7s rostopic echo -p /MotorNode/baselink_odom_relative": FakeCommandResult(
                ok=False,
                stdout="%time,field.pose.pose.position.x,field.pose.pose.position.y,field.pose.pose.orientation.z\n1.0,0.0,0.0,0.0\n2.0,0.12,0.03,0.0\n",
            ),
            "tmp_file=\"$(mktemp)\"": FakeCommandResult(
                stdout="%time,field.pose.pose.position.x,field.pose.pose.position.y,field.pose.pose.orientation.z\n1.0,0.0,0.0,0.0\n2.0,0.09,0.02,0.0\n",
            ),
        }
        self.lookup.update(overrides or {})

    def run(self, command, cwd=None, check=True):
        command_text = command if isinstance(command, str) else " ".join(command)
        self.commands.append(command_text)
        for needle, result in self.lookup.items():
            if needle in command_text:
                return result
        return FakeCommandResult(ok=False, stderr="unexpected command: {}".format(command_text))

    def run_remote(self, ssh_config, remote_command, check=True, batch_mode=None, connect_timeout=5):
        return self.run(remote_command, check=check)


class LiveProbeTest(unittest.TestCase):
    """Verify live probe inference and site updates."""

    def test_probe_infers_pose_and_motion_from_fake_runner(self):
        site_config = default_site_config()
        runner = FakeRunner()

        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=5,
            exercise_cmd_vel=True,
            runner=runner,
            force_remote=True,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["inferred_capabilities"]["scan"])
        self.assertTrue(result["inferred_capabilities"]["camera"])
        self.assertTrue(result["inferred_capabilities"]["tof"])
        self.assertTrue(result["inferred_capabilities"]["imu"])
        self.assertTrue(result["inferred_capabilities"]["pose"])
        self.assertTrue(result["inferred_capabilities"]["motion"])
        self.assertTrue(result["observed"]["tf"]["ok"])
        self.assertEqual(result["observed"]["tf"]["missing_edges"], [])
        self.assertEqual(result["config_mismatch_suggestions"], [])
        self.assertEqual(
            result["observed"]["services"]["vendor_low_battery_dock"]["details"]["type"],
            "roller_eye/nav_low_bat",
        )
        self.assertEqual(result["observed"]["command_exercise"]["forward_axis"], "y")
        self.assertEqual(result["observed"]["command_exercise"]["dominant_axis"], "x")
        self.assertGreater(result["observed"]["command_exercise"]["delta_x"], 0.0)
        self.assertGreater(result["observed"]["command_exercise"]["delta_x"], result["observed"]["command_exercise"]["delta_y"])
        self.assertTrue(any("timeout 8s rostopic list" in command for command in runner.commands))
        self.assertTrue(any("timeout 8s rosnode list" in command for command in runner.commands))
        self.assertTrue(any("timeout 5s rostopic info /scan" in command for command in runner.commands))

    def test_probe_suggests_ttys4_and_vio_odom_when_defaults_are_wrong(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["devices"]["lidar"] = "/dev/ttyUSB0"
        site_config["roles"]["scout"]["topics"]["odom"] = "/odom"
        runner = FakeRunner(
            overrides={
                "rostopic list": FakeCommandResult(
                    stdout="/scan\n/camera/image_raw/compressed\n/MotorNode/vio_odom_relative\n/cmd_vel_force\n",
                ),
            }
        )

        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=0,
            exercise_cmd_vel=False,
            runner=runner,
            force_remote=True,
        )

        self.assertTrue(result["ok"])
        suggestions = {item["path"]: item["suggested"] for item in result["config_mismatch_suggestions"]}
        self.assertEqual(suggestions["roles.scout.devices.lidar"], "/dev/ttyS4")
        self.assertEqual(suggestions["roles.scout.topics.odom"], "/MotorNode/vio_odom_relative")

    def test_probe_reports_missing_tf_separately_from_odom(self):
        site_config = default_site_config()
        runner = FakeRunner(
            overrides={
                "rostopic list": FakeCommandResult(
                    stdout="/scan\n/camera/image_raw/compressed\n/MotorNode/baselink_odom_relative\n/cmd_vel_force\n",
                ),
            }
        )

        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=0,
            exercise_cmd_vel=False,
            runner=runner,
            force_remote=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["observed"]["topics"]["odom"]["selected"], "/MotorNode/baselink_odom_relative")
        self.assertFalse(result["observed"]["tf"]["ok"])
        self.assertEqual(
            result["observed"]["tf"]["missing_edges"],
            [
                {"parent": "base_link", "child": "base_laser"},
                {"parent": "odom", "child": "base_link"},
            ],
        )

    def test_probe_progress_reports_ordered_work_and_skipped_motion_observation(self):
        site_config = default_site_config()
        runner = FakeRunner()
        progress = []

        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=0,
            exercise_cmd_vel=False,
            runner=runner,
            force_remote=True,
            progress=progress.append,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(progress)
        joined = "\n".join(progress)
        self.assertIn("Starting live Scout probe", progress[0])
        self.assertIn("Probe work plan", joined)
        self.assertIn("remaining ROS timeout budget <=", joined)
        self.assertIn("Topic lidar_scan /scan: reading publishers/subscribers", joined)
        self.assertIn("Motion observation skipped (--observe-motion 0)", joined)
        self.assertIn("Live Scout probe complete", joined)
        self.assertLess(
            joined.index("Probe work plan"),
            joined.index("Topic lidar_scan /scan: reading publishers/subscribers"),
        )
        self.assertLess(
            joined.index("Motion observation skipped (--observe-motion 0)"),
            joined.index("Live Scout probe complete"),
        )

    def test_apply_probe_suggestions_updates_site_inventory(self):
        site_config = default_site_config()
        site_config["roles"]["scout"]["capabilities"]["pose"] = False
        probe_result = {
            "config_mismatch_suggestions": [
                {
                    "path": "roles.scout.capabilities.pose",
                    "current": False,
                    "suggested": True,
                    "reason": "Live probe confirmed pose.",
                },
                {
                    "path": "roles.scout.topics.vendor_cmd_vel",
                    "current": "/cmd_vel",
                    "suggested": "/cmd_vel_force",
                    "reason": "Live probe found /cmd_vel_force.",
                },
            ]
        }

        updated = apply_probe_suggestions(site_config, probe_result)

        self.assertTrue(updated["roles"]["scout"]["capabilities"]["pose"])
        self.assertEqual(updated["roles"]["scout"]["topics"]["vendor_cmd_vel"], "/cmd_vel_force")


if __name__ == "__main__":
    unittest.main()

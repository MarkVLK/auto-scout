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
        self.lookup = {
            "printf 'ROS_MASTER_URI=%s": FakeCommandResult(
                stdout="ROS_MASTER_URI=http://scout.example.test:11311\nROS_HOSTNAME=scout.example.test\nROS_IP=\n",
            ),
            "rostopic list": FakeCommandResult(
                stdout="/scan\n/camera/image_raw/compressed\n/MotorNode/baselink_odom_relative\n/cmd_vel_force\n",
            ),
            "rosnode list": FakeCommandResult(stdout="/MotorNode\n"),
            "test -e /dev/video0": FakeCommandResult(stdout="present\n"),
            "test -e /dev/ttyS4": FakeCommandResult(stdout="present\n"),
            "test -e /dev/ttyUSB0": FakeCommandResult(stdout="missing\n"),
            "rostopic info /scan": FakeCommandResult(stdout="Type: sensor_msgs/LaserScan\nPublishers:\n * /ld19\nSubscribers:\n"),
            "rostopic hz -w 5 /scan": FakeCommandResult(ok=False, stdout="average rate: 10.0\n"),
            "rostopic echo -n 1 /scan": FakeCommandResult(stdout="header:\n"),
            "rostopic info /camera/image_raw/compressed": FakeCommandResult(stdout="Type: sensor_msgs/CompressedImage\nPublishers:\n * /camera\nSubscribers:\n"),
            "rostopic hz -w 5 /camera/image_raw/compressed": FakeCommandResult(ok=False, stdout="average rate: 5.0\n"),
            "rostopic echo -n 1 /camera/image_raw/compressed": FakeCommandResult(stdout="header:\n"),
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

        result = probe_scout_capabilities(
            site_config,
            observe_motion_seconds=5,
            exercise_cmd_vel=True,
            runner=FakeRunner(),
            force_remote=True,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["inferred_capabilities"]["scan"])
        self.assertTrue(result["inferred_capabilities"]["camera"])
        self.assertTrue(result["inferred_capabilities"]["pose"])
        self.assertTrue(result["inferred_capabilities"]["motion"])
        self.assertEqual(result["config_mismatch_suggestions"], [])
        self.assertEqual(result["observed"]["command_exercise"]["forward_axis"], "y")
        self.assertEqual(result["observed"]["command_exercise"]["dominant_axis"], "x")
        self.assertGreater(result["observed"]["command_exercise"]["delta_x"], 0.0)
        self.assertGreater(result["observed"]["command_exercise"]["delta_x"], result["observed"]["command_exercise"]["delta_y"])

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

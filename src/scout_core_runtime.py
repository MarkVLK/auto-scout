#!/usr/bin/env python2
"""Consolidated Scout-side Auto-Scout runtime process."""

from __future__ import print_function

import argparse

from config_utils import load_scout_config
from scout_runtime_agent import ScoutRuntimeHeartbeat
from scout_runtime_config import load_site_config
from scout_battery_dock_guard import ScoutBatteryDockGuardNode
from scout_imu_bridge import ScoutImuBridge
from scout_motion_bridge import ScoutMotionBridge
from scout_odom_bridge import ScoutOdomBridge
from scout_safety_filter import ScoutSafetyFilterNode
from scout_tof_bridge import ScoutToFBridge


def _timer_period(hz, fallback_hz):
    try:
        value = float(hz)
    except (TypeError, ValueError):
        value = float(fallback_hz)
    if value <= 0.0:
        value = float(fallback_hz)
    return 1.0 / value


class ScoutCoreRuntime(object):
    """Own all lightweight Scout-side bridges and guards inside one ROS process."""

    def __init__(self, config_path=None, site_path=None):
        try:
            import rospy
        except ImportError as exc:
            raise SystemExit("Scout core runtime requires ROS Python packages: {}".format(exc))

        self.rospy = rospy
        rospy.init_node("scout_core_runtime", anonymous=False)
        config_path = rospy.get_param("~config_file", config_path)
        site_path = rospy.get_param("~site_file", site_path)
        self.config, self.config_path = load_scout_config(config_path)
        self.site_config, self.site_path = load_site_config(site_path)

        self.heartbeat = ScoutRuntimeHeartbeat(
            site_path=self.site_path,
            site_config=self.site_config,
            init_node=False,
        )
        self.tof_bridge = ScoutToFBridge(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~tof",
        )
        self.imu_bridge = ScoutImuBridge(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~imu",
        )
        self.odom_bridge = ScoutOdomBridge(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~odom",
        )
        self.battery_guard = ScoutBatteryDockGuardNode(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~battery",
        )
        self.safety_filter = ScoutSafetyFilterNode(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~safety",
        )
        self.motion_bridge = ScoutMotionBridge(
            config_path=self.config_path,
            site_path=self.site_path,
            config=self.config,
            site_config=self.site_config,
            init_node=False,
            param_prefix="~motion",
        )
        self.timers = []

    def start(self):
        self.rospy.loginfo("Scout core runtime active")
        for component in [
            self.tof_bridge,
            self.imu_bridge,
            self.odom_bridge,
            self.battery_guard,
            self.safety_filter,
            self.motion_bridge,
        ]:
            component.log_active()

        self.heartbeat.tick()
        self.battery_guard.tick()
        self.safety_filter.tick()
        self.timers = [
            self.rospy.Timer(self.rospy.Duration(2.0), self.heartbeat.tick),
            self.rospy.Timer(
                self.rospy.Duration(_timer_period(self.battery_guard.publish_hz, 1.0)),
                self.battery_guard.tick,
            ),
            self.rospy.Timer(
                self.rospy.Duration(_timer_period(self.safety_filter.publish_hz, 10.0)),
                self.safety_filter.tick,
            ),
        ]
        self.rospy.spin()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    runtime = ScoutCoreRuntime(config_path=args.config, site_path=args.site)
    runtime.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

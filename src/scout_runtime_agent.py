#!/usr/bin/env python2
"""Scout runtime heartbeat agent."""

import argparse
import json
import socket
from datetime import datetime

from scout_runtime_config import load_site_config
from scout_runtime_config import role_config


def _utc_timestamp():
    return datetime.utcnow().isoformat() + "Z"


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=None)
    return parser


class ScoutRuntimeHeartbeat(object):
    def __init__(self, site_path=None, site_config=None, init_node=True):
        try:
            import rospy
            from std_msgs.msg import String
        except ImportError as exc:
            raise SystemExit("rospy is required to run the scout runtime agent: {}".format(exc))

        self.rospy = rospy
        self.String = String
        if init_node:
            rospy.init_node("scout_runtime_agent", anonymous=False)

        if site_config is None:
            site_config, resolved_site_path = load_site_config(site_path)
        else:
            resolved_site_path = site_path
        role_settings = role_config(site_config, "scout")
        self.payload = {
            "role": "scout",
            "hostname": socket.gethostname(),
            "site_config": resolved_site_path,
            "workspace_dir": role_settings.get("workspace_dir"),
            "capabilities": role_settings.get("capabilities", {}),
            "adapters": role_settings.get("adapters", {}),
            "timestamp": _utc_timestamp(),
        }
        self.publisher = rospy.Publisher("/scout/runtime_status", String, queue_size=1, latch=True)

    def tick(self, event=None):
        self.payload["timestamp"] = _utc_timestamp()
        self.publisher.publish(json.dumps(self.payload, sort_keys=True))

    def run(self):
        rate = self.rospy.Rate(0.5)
        while not self.rospy.is_shutdown():
            self.tick()
            rate.sleep()


def run_heartbeat(site_path=None):
    heartbeat = ScoutRuntimeHeartbeat(site_path=site_path, init_node=True)
    heartbeat.run()


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    run_heartbeat(args.site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

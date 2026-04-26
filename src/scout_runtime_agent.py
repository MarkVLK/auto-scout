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


def run_heartbeat(site_path=None):
    try:
        import rospy
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit("rospy is required to run the scout runtime agent: {}".format(exc))

    site_config, resolved_site_path = load_site_config(site_path)
    role_settings = role_config(site_config, "scout")
    payload = {
        "role": "scout",
        "hostname": socket.gethostname(),
        "site_config": resolved_site_path,
        "workspace_dir": role_settings.get("workspace_dir"),
        "capabilities": role_settings.get("capabilities", {}),
        "adapters": role_settings.get("adapters", {}),
        "timestamp": _utc_timestamp(),
    }

    rospy.init_node("scout_runtime_agent", anonymous=False)
    publisher = rospy.Publisher("/scout/runtime_status", String, queue_size=1, latch=True)
    rate = rospy.Rate(0.5)

    while not rospy.is_shutdown():
        payload["timestamp"] = _utc_timestamp()
        publisher.publish(json.dumps(payload, sort_keys=True))
        rate.sleep()


def main(argv=None):
    args, _ = build_parser().parse_known_args(argv)
    run_heartbeat(args.site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

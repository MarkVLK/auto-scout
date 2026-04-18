"""Role-specific heartbeat nodes for Scout and companion runtimes."""

import argparse
import json
import socket
from datetime import datetime, timezone

from auto_scout.site_config import load_site_config, role_config


def _status_payload(role, site_path):
    site_config, _ = load_site_config(site_path)
    role_settings = role_config(site_config, role)
    return {
        "role": role,
        "hostname": socket.gethostname(),
        "site_config": site_path,
        "workspace_dir": role_settings.get("workspace_dir"),
        "capabilities": role_settings.get("capabilities", {}),
        "adapters": role_settings.get("adapters", {}),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def run_heartbeat(role, site_path=None):
    """Publish a runtime heartbeat for the requested role."""
    try:
        import rospy
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit("rospy is required to run the {} runtime agent: {}".format(role, exc))

    payload = _status_payload(role, site_path)
    node_name = "{}_runtime_agent".format(role)
    topic_name = "/{}/runtime_status".format(role)

    rospy.init_node(node_name, anonymous=False)
    publisher = rospy.Publisher(topic_name, String, queue_size=1, latch=True)
    rate = rospy.Rate(0.5)

    while not rospy.is_shutdown():
        payload["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        publisher.publish(json.dumps(payload, sort_keys=True))
        rate.sleep()


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default=None)
    return parser

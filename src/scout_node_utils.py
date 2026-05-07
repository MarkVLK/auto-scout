#!/usr/bin/env python2
"""Small helpers shared by Scout-side ROS nodes."""

from config_utils import load_scout_config
from scout_runtime_config import load_site_config


def private_param(param_prefix, name):
    prefix = param_prefix or "~"
    return "{}/{}".format(prefix.rstrip("/"), name)


def load_runtime_configs(rospy, config_path=None, site_path=None, config=None, site_config=None, param_prefix=None):
    resolved_config_path = config_path
    resolved_site_path = site_path
    if config is None:
        resolved_config_path = rospy.get_param(private_param(param_prefix, "config_file"), config_path)
        config, resolved_config_path = load_scout_config(resolved_config_path)
    if site_config is None:
        resolved_site_path = rospy.get_param(private_param(param_prefix, "site_file"), site_path)
        site_config, resolved_site_path = load_site_config(resolved_site_path)
    return config, resolved_config_path, site_config, resolved_site_path

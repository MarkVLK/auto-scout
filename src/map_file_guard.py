#!/usr/bin/env python2
"""Fail fast when localization mode is requested without a saved map."""

from __future__ import print_function

import os

import rospy


def main():
    rospy.init_node("map_file_guard", anonymous=False)
    map_file = rospy.get_param("~map_file", "")
    if map_file and os.path.isfile(map_file):
        rospy.loginfo("Localization map file is present: %s", map_file)
        return 0

    rospy.logfatal("Localization mode requires an existing map file, but '{}' was not found.".format(map_file))
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())

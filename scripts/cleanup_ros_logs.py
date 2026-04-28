#!/usr/bin/env python3
"""Bound ROS log directories by age and total size."""

import argparse
import os
import shutil
import sys
import time


DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MAX_BYTES = 100 * 1024 * 1024


def _entry_size(path):
    """Return apparent disk usage for a file tree without following symlinks."""
    try:
        stat_result = os.lstat(path)
    except OSError:
        return 0

    if not os.path.isdir(path) or os.path.islink(path):
        return stat_result.st_size

    total = stat_result.st_size
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        for name in list(dirs):
            child = os.path.join(root, name)
            try:
                child_stat = os.lstat(child)
            except OSError:
                dirs.remove(name)
                continue
            total += child_stat.st_size
            if os.path.islink(child):
                dirs.remove(name)
        for name in files:
            total += _entry_size(os.path.join(root, name))
    return total


def _remove_path(path, dry_run, actions):
    if not os.path.lexists(path):
        return
    actions.append("remove {}".format(path))
    if dry_run:
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def _remove_old_entries(root, cutoff, dry_run, actions):
    old_directories = []
    for current_root, dirs, _files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs:
            path = os.path.join(current_root, name)
            try:
                mtime = os.lstat(path).st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                old_directories.append(path)

    for path in sorted(old_directories, key=lambda item: item.count(os.sep), reverse=True):
        _remove_path(path, dry_run, actions)

    for current_root, dirs, files in os.walk(root, topdown=False, followlinks=False):
        names = list(files) + list(dirs)
        for name in names:
            path = os.path.join(current_root, name)
            if not os.path.lexists(path):
                continue
            try:
                mtime = os.lstat(path).st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                _remove_path(path, dry_run, actions)


def _candidate_entries(root):
    candidates = []
    try:
        names = os.listdir(root)
    except OSError:
        return candidates

    for name in names:
        if name in [".", ".."]:
            continue
        path = os.path.join(root, name)
        if not os.path.lexists(path):
            continue
        try:
            stat_result = os.lstat(path)
        except OSError:
            continue
        candidates.append((stat_result.st_mtime, path))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates


def cleanup_path(root, max_age_days, max_bytes, dry_run=False):
    actions = []
    if not os.path.exists(root):
        actions.append("skip missing {}".format(root))
        return actions
    if not os.path.isdir(root):
        actions.append("skip non-directory {}".format(root))
        return actions

    cutoff = time.time() - (float(max_age_days) * 24 * 60 * 60)
    _remove_old_entries(root, cutoff, dry_run, actions)

    total = _entry_size(root)
    for _mtime, path in _candidate_entries(root):
        if total <= max_bytes:
            break
        size = _entry_size(path)
        _remove_path(path, dry_run, actions)
        total -= size

    actions.append("usage {} {}".format(root, min(total, max_bytes) if dry_run else _entry_size(root)))
    return actions


def _env_int(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    return int(value)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=[],
        help="ROS log directory to clean; may be repeated.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=_env_int("AUTO_SCOUT_ROS_LOG_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS),
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=_env_int("AUTO_SCOUT_ROS_LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned removals without deleting.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    paths = list(args.paths)
    env_path = os.environ.get("ROS_LOG_DIR") or os.environ.get("AUTO_SCOUT_ROS_LOG_DIR")
    if env_path and env_path not in paths:
        paths.insert(0, env_path)
    if not paths:
        paths.append(os.path.expanduser("~/.ros/log"))

    for path in paths:
        for action in cleanup_path(path, args.max_age_days, args.max_bytes, dry_run=args.dry_run):
            print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

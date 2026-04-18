#!/usr/bin/env python3
"""Companion runtime heartbeat agent."""

from auto_scout.runtime.heartbeat import build_parser, run_heartbeat


def main(argv=None):
    args = build_parser().parse_args(argv)
    run_heartbeat("companion", args.site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

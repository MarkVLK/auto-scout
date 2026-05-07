#!/usr/bin/env python
"""Compatibility wrapper for source-run companion notification helpers."""

from __future__ import print_function

from auto_scout.notifications import build_mission_success_payload
from auto_scout.notifications import build_preflight_refusal_payload
from auto_scout.notifications import build_resource_alert_payload
from auto_scout.notifications import build_test_notification_payload
from auto_scout.notifications import companion_notification_webhook_url
from auto_scout.notifications import DEFAULT_TEST_MESSAGE


__all__ = [
    "DEFAULT_TEST_MESSAGE",
    "build_mission_success_payload",
    "build_preflight_refusal_payload",
    "build_resource_alert_payload",
    "build_test_notification_payload",
    "companion_notification_webhook_url",
]

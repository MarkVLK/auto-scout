#!/usr/bin/env python
"""Slack notification helpers for companion-side mission reporting."""

from __future__ import print_function


DEFAULT_TEST_MESSAGE = "Auto-Scout Slack notification test"


def companion_notification_webhook_url(site_config):
    """Return the companion Slack incoming webhook URL, if configured."""
    roles = site_config.get("roles", {}) if isinstance(site_config, dict) else {}
    companion = roles.get("companion", {}) if isinstance(roles, dict) else {}
    notifications = companion.get("notifications", {}) if isinstance(companion, dict) else {}
    return str(notifications.get("webhook_url") or "").strip()


def build_mission_success_payload(mission_name, artifact_dir, photo_path, return_result, timestamp):
    """Return a Slack-compatible payload for a completed mission."""
    mission = str(mission_name or "smoke_loop")
    title = "Auto-Scout mission passed: {}".format(mission)
    fields = [
        _field("Mission", mission),
        _field("Result", "pass"),
        _field("Artifact", artifact_dir),
        _field("Photo", photo_path),
        _field("Return", _return_summary(return_result)),
        _field("Timestamp", timestamp),
    ]
    return _payload(title, fields)


def build_preflight_refusal_payload(result):
    """Return a Slack-compatible payload for a refused mission start."""
    payload = result if isinstance(result, dict) else {}
    mission = str(payload.get("mission") or "smoke_loop")
    reason = str(payload.get("reason") or "preflight_failed")
    title = "Auto-Scout mission blocked: {} ({})".format(mission, reason)
    fields = [
        _field("Mission", mission),
        _field("Reason", reason),
        _field("Battery", _battery_summary(payload.get("battery_percent"))),
        _field("Charging", payload.get("charging")),
        _field("Guard mode", payload.get("battery_guard_mode")),
        _field("Required battery", _battery_summary(payload.get("mission_start_min_battery_level"))),
        _field("Artifact", payload.get("artifact_dir")),
        _field("Timestamp", payload.get("timestamp")),
    ]
    return _payload(title, fields)


def build_test_notification_payload(message=None, timestamp=None):
    """Return a Slack-compatible payload for a manual notification test."""
    text = str(message or DEFAULT_TEST_MESSAGE)
    fields = [_field("Message", text)]
    if timestamp:
        fields.append(_field("Timestamp", timestamp))
    return _payload(text, fields)


def build_resource_alert_payload(report, forced=False):
    """Return a Slack-compatible payload for resource health alerts."""
    payload = report if isinstance(report, dict) else {}
    alerts = payload.get("alerts", []) if isinstance(payload.get("alerts", []), list) else []
    status = str(payload.get("status") or ("critical" if alerts else "ok"))
    title = "Auto-Scout resource alert: {}".format(status)
    if forced and not alerts:
        title = "Auto-Scout resource check test: ok"
    elif not alerts:
        title = "Auto-Scout resource alert recovered"

    fields = [
        _field("Status", status),
        _field("Alert count", len(alerts)),
        _field("Timestamp", payload.get("timestamp")),
    ]
    for alert in alerts[:7]:
        if not isinstance(alert, dict):
            continue
        fields.append(_field(alert.get("summary", "Alert"), alert.get("detail", "")))
    if len(alerts) > 7:
        fields.append(_field("Additional alerts", len(alerts) - 7))
    return _payload(title, fields)


def _payload(title, fields):
    filtered_fields = [item for item in fields if item is not None]
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*{}*".format(_markdown_value(title)),
            },
        }
    ]
    if filtered_fields:
        blocks.append({"type": "section", "fields": filtered_fields[:10]})
    return {
        "text": str(title),
        "blocks": blocks,
    }


def _field(label, value):
    value_text = _value_text(value)
    if value_text == "":
        return None
    return {
        "type": "mrkdwn",
        "text": "*{}*\n{}".format(_markdown_value(label), _markdown_value(value_text)),
    }


def _value_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _battery_summary(value):
    try:
        return "{:.1f}%".format(float(value))
    except (TypeError, ValueError):
        return ""


def _return_summary(return_result):
    if not isinstance(return_result, dict):
        return _value_text(return_result)
    mode = return_result.get("mode")
    waypoint = return_result.get("waypoint")
    if mode and waypoint:
        return "{}: {}".format(mode, waypoint)
    return _value_text(mode or return_result)


def _markdown_value(value):
    text = _value_text(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

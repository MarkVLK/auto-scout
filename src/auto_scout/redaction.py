"""Redaction helpers for user-facing reports and persisted artifacts."""

from copy import deepcopy
import re


REDACTED_VALUE = "<redacted>"
SENSITIVE_KEYS = {
    "webhook_url",
}
SENSITIVE_PATTERNS = [
    re.compile(r"https://hooks\.slack\.com/services/[^\s\"'<>]+"),
    re.compile(r"hooks\.slack\.com/services/[^\s\"'<>]+"),
    re.compile(r"/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+"),
]


def redact_sensitive(value):
    """Return a copy of ``value`` with sensitive fields redacted."""
    return _redact(deepcopy(value), parent_key=None)


def _redact(value, parent_key=None):
    if _is_sensitive_key(parent_key):
        return REDACTED_VALUE if value not in [None, ""] else value

    if isinstance(value, dict):
        return {key: _redact(item, parent_key=key) for key, item in value.items()}

    if isinstance(value, list):
        return [_redact(item, parent_key=parent_key) for item in value]

    if isinstance(value, str):
        return _redact_string(value)

    return value


def _is_sensitive_key(key):
    return str(key or "").lower() in SENSITIVE_KEYS


def _redact_string(value):
    redacted = value
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    return redacted

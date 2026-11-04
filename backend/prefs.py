"""Tolerant reads of saved settings: QSettings ini values come back as
strings, bools or lists, and a damaged file must never stop the dashboard."""

import json

_TRUE = ("true", "1", "yes")
_FALSE = ("false", "0", "no", "")


def as_bool(value, default=False):
    """A saved true/false setting as a bool; default when missing or unreadable."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
    return default


def as_json(value, kind, default):
    """A saved JSON setting if it parses to the given type, else default (never raises)."""
    try:
        result = json.loads(str(value))
    except (ValueError, TypeError, RecursionError):
        return default
    return result if isinstance(result, kind) else default
